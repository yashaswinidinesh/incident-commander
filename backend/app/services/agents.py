"""
4 specialized incident response agents.
"""
import asyncio, json, re, time
from abc import ABC, abstractmethod
from datetime import datetime
import httpx
from app.core.config import settings

SYS = """You are a specialized DevOps incident response agent.
Output ONLY valid JSON. Never fabricate log entries, metrics, or deploy records.
Clearly mark hypotheses vs confirmed facts. Confidence 0.0-1.0."""


class AgentOutput:
    def __init__(self, role, summary, evidence, structured, confidence):
        self.role = role; self.summary = summary; self.evidence = evidence
        self.structured = structured; self.confidence = confidence
        self.timestamp = datetime.utcnow().isoformat()
    def to_dict(self): return {k: v for k, v in self.__dict__.items()}


class BaseAgent(ABC):
    def __init__(self, role):
        self.role = role; self.model = settings.DEFAULT_MODEL
        self._client = httpx.AsyncClient(timeout=90)

    async def _call_llm(self, system, user, context=None):
        if not settings.OPENAI_API_KEY: return await self._mock(context or {})
        r = await self._client.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": self.model,
                  "messages": [{"role":"system","content":system},{"role":"user","content":user}],
                  "temperature": 0.1, "response_format": {"type": "json_object"}})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    async def _mock(self, ctx):
        await asyncio.sleep(0.1)

        if self.role == "log_analyst":
            logs = str(ctx.get("logs", ""))[:6000]
            rules = [
                ("Connection pool exhausted", "critical"),
                ("Timeout connecting", "high"),
                ("Circuit breaker OPEN", "high"),
                ("OOMKilled", "critical"),
                ("CrashLoopBackOff", "critical"),
                ("P1 alert", "critical"),
            ]
            patterns = []
            timeline = []
            services = set()
            for line in logs.splitlines():
                service_match = re.search(r"\[([^\]]+)\]", line)
                if service_match:
                    services.add(service_match.group(1))
                if re.search(r"\b(ERROR|WARN|CRITICAL|FATAL)\b", line):
                    timestamp = line.split(maxsplit=1)[0] if line else ""
                    timeline.append({"time": timestamp, "event": line, "source": "log_line"})
                for label, severity in rules:
                    if label.lower() in line.lower():
                        existing = next((p for p in patterns if p["pattern"] == label), None)
                        if existing:
                            existing["count"] += 1
                        else:
                            patterns.append({"pattern": label, "count": 1,
                                             "first_seen": line.split(maxsplit=1)[0],
                                             "severity": severity})
            return json.dumps({
                "error_patterns": patterns,
                "affected_services": sorted(services),
                "timeline": timeline,
                "anomalies": [p["pattern"] for p in patterns],
                "null_hypotheses_ruled_out": [],
                "confidence": 0.8 if patterns else 0.2,
            })

        if self.role == "deploy_history":
            deploys = ctx.get("deploy_history", [])
            log_data = ctx.get("log_analyst", {}).get("structured", {})
            affected = set(log_data.get("affected_services", []))
            logs = str(ctx.get("logs", ""))
            incident_time = None
            if logs:
                try:
                    incident_time = datetime.fromisoformat(logs.splitlines()[0].split()[0].replace("Z", "+00:00"))
                except ValueError:
                    pass
            recent = []
            suspicious = []
            for deploy in deploys:
                entry = dict(deploy)
                service = entry.get("service", "")
                reason = ""
                confidence = 0.0
                deploy_time = None
                try:
                    deploy_time = datetime.fromisoformat(str(entry.get("time", "")).replace("Z", "+00:00"))
                except ValueError:
                    pass
                if service in affected:
                    reason = "The deployed service also appears in the incident logs."
                    confidence = 0.6
                    if incident_time and deploy_time:
                        hours_before = (incident_time - deploy_time).total_seconds() / 3600
                        if 0 <= hours_before <= 2:
                            reason = f"The service was deployed {hours_before:.1f} hours before the first incident log."
                            confidence = 0.85
                entry["risk"] = "high" if confidence >= 0.8 else "medium" if confidence else "low"
                recent.append(entry)
                if reason:
                    suspicious.append({"deploy": deploy, "reason": reason, "confidence": confidence})
            rollback_candidates = []
            for item in suspicious:
                deploy = item["deploy"]
                rollback_candidates.append({
                    "service": deploy.get("service", "unknown"),
                    "target_version": "previous known-good version",
                    "rationale": item["reason"],
                })
            return json.dumps({
                "recent_deploys": recent,
                "suspicious_deploys": suspicious,
                "correlation_with_incident": "A recent deploy touched an affected service." if suspicious else "No direct deploy correlation found.",
                "rollback_candidates": rollback_candidates,
                "confidence": max((d["confidence"] for d in suspicious), default=0.6),
            })

        if self.role == "root_cause":
            log_data = ctx.get("log_analyst", {}).get("structured", {})
            deploy_data = ctx.get("deploy_history", {}).get("structured", {})
            patterns = [p.get("pattern", "") for p in log_data.get("error_patterns", [])]
            logs = str(ctx.get("logs", ""))
            evidence = [line for line in logs.splitlines() if any(p.lower() in line.lower() for p in patterns)]
            suspicious = deploy_data.get("suspicious_deploys", [])
            if any("connection pool" in p.lower() for p in patterns):
                cause = "Payment-service database connection pool exhaustion caused cascading timeouts and restarts."
                if suspicious:
                    evidence.append(suspicious[0].get("reason", ""))
                hypotheses = [{
                    "rank": 1,
                    "hypothesis": cause,
                    "supporting_evidence": evidence[:6],
                    "contradicting_evidence": [],
                    "confidence": 0.85 if suspicious else 0.75,
                    "category": "infrastructure",
                }]
                confidence = hypotheses[0]["confidence"]
            elif patterns:
                cause = f"{patterns[0]} is the strongest observed failure signal."
                hypotheses = [{"rank": 1, "hypothesis": cause,
                               "supporting_evidence": evidence[:6],
                               "contradicting_evidence": [], "confidence": 0.65,
                               "category": "infrastructure"}]
                confidence = 0.65
            else:
                cause, hypotheses, confidence = "Insufficient log evidence", [], 0.2
            return json.dumps({"hypotheses": hypotheses, "most_likely_cause": cause,
                               "blast_radius": ", ".join(log_data.get("affected_services", [])) or "unknown",
                               "time_to_resolution_estimate": "10-20 minutes (estimate)",
                               "confidence": confidence})

        if self.role == "remediation":
            root_data = ctx.get("root_cause", {}).get("structured", {})
            cause = root_data.get("most_likely_cause", "Insufficient log evidence")
            pool_issue = "connection pool" in cause.lower()
            actions = [
                {"priority": 1, "action": "Inspect payment-service connection usage and database pool saturation.",
                 "command": "kubectl logs deployment/payment-service -n <namespace> --since=30m",
                 "risk": "low", "requires_approval": False,
                 "rationale": "Collect current evidence before making production changes."},
                {"priority": 2, "action": "Consider rolling payment-service back to the previous known-good version.",
                 "command": "kubectl rollout undo deployment/payment-service -n <namespace>",
                 "risk": "high", "requires_approval": True,
                 "rationale": cause if pool_issue else "Validate the proposed root cause before rollback."},
            ]
            return json.dumps({"immediate_actions": actions,
                               "rollback_plan": [{"step": 1, "action": "Review deployment and database metrics before changing capacity.", "command": "kubectl rollout history deployment/payment-service -n <namespace>"}],
                               "monitoring_steps": ["Watch database active connections, pool wait time, and payment-service restart count."],
                               "post_incident_tasks": ["Add alerts for connection-pool saturation and repeated pod restarts."],
                               "estimated_recovery_time": "10-20 minutes (estimate)",
                               "confidence": 0.7})

        return json.dumps({"confidence": 0.2})

    @abstractmethod
    async def run(self, ctx): pass


class LogAnalystAgent(BaseAgent):
    def __init__(self): super().__init__("log_analyst")
    async def run(self, ctx):
        logs = ctx.get("logs", "")[:6000]
        raw = await self._call_llm(SYS, f"""Analyze these logs for an active incident. Output JSON:
{{
  "error_patterns": [{{"pattern": str, "count": int, "first_seen": str, "severity": str}}],
  "affected_services": [str],
  "timeline": [{{"time": str, "event": str, "source": "log_line|inferred"}}],
  "anomalies": [str],
  "null_hypotheses_ruled_out": [str],
  "confidence": float
}}
Logs:\n{logs}""", ctx)
        d = json.loads(raw)
        return AgentOutput(self.role,
            f"Found {len(d.get('error_patterns',[]))} error patterns across {len(d.get('affected_services',[]))} services.",
            [{"text": p.get("pattern"), "source": "logs", "location": p.get("first_seen","")}
             for p in d.get("error_patterns", [])], d, d.get("confidence", 0.8))


class DeployHistoryAgent(BaseAgent):
    def __init__(self): super().__init__("deploy_history")
    async def run(self, ctx):
        deploys = ctx.get("deploy_history", [])
        log_summary = ctx.get("log_analyst", {}).get("summary", "")
        raw = await self._call_llm(SYS, f"""Analyze deploy history in context of the incident. Output JSON:
{{
  "recent_deploys": [{{"service": str, "version": str, "time": str, "author": str, "risk": "low|medium|high"}}],
  "suspicious_deploys": [{{"deploy": dict, "reason": str, "confidence": float}}],
  "correlation_with_incident": str,
  "rollback_candidates": [{{"service": str, "target_version": str, "rationale": str}}],
  "confidence": float
}}
Recent deploys: {json.dumps(deploys[:10])}
Log analyst summary: {log_summary}""", ctx)
        d = json.loads(raw)
        return AgentOutput(self.role,
            f"{len(d.get('suspicious_deploys',[]))} suspicious deploys. {len(d.get('rollback_candidates',[]))} rollback candidates.",
            [{"text": x.get("reason",""), "source": "deploy_log", "location": x.get("deploy",{}).get("time","")}
             for x in d.get("suspicious_deploys",[])], d, d.get("confidence", 0.75))


class RootCauseAgent(BaseAgent):
    def __init__(self): super().__init__("root_cause")
    async def run(self, ctx):
        log_data = ctx.get("log_analyst", {}).get("structured", {})
        deploy_data = ctx.get("deploy_history", {}).get("structured", {})
        raw = await self._call_llm(SYS, f"""Synthesize evidence into ranked root-cause hypotheses. Output JSON:
{{
  "hypotheses": [{{
    "rank": int, "hypothesis": str,
    "supporting_evidence": [str], "contradicting_evidence": [str],
    "confidence": float, "category": "deploy|dependency|infrastructure|code|data|external"
  }}],
  "most_likely_cause": str,
  "blast_radius": str,
  "time_to_resolution_estimate": str,
  "confidence": float
}}
Log analysis: {json.dumps(log_data)[:2000]}
Deploy analysis: {json.dumps(deploy_data)[:2000]}""", ctx)
        d = json.loads(raw)
        return AgentOutput(self.role,
            f"Most likely: {d.get('most_likely_cause','Unknown')} ({d.get('confidence',0):.0%}). {len(d.get('hypotheses',[]))} hypotheses.",
            [{"text": e, "source": "correlation", "location": ""}
             for h in d.get("hypotheses",[])[:1] for e in h.get("supporting_evidence",[])],
            d, d.get("confidence", 0.0))


class RemediationAgent(BaseAgent):
    def __init__(self): super().__init__("remediation")
    async def run(self, ctx):
        rc = ctx.get("root_cause", {}).get("structured", {})
        deploy = ctx.get("deploy_history", {}).get("structured", {})
        raw = await self._call_llm(SYS, f"""Draft a ranked remediation plan. Output JSON:
{{
    "immediate_actions": [{{
        "priority": int, "action": str, "command": str,
        "risk": "low|medium|high", "requires_approval": bool, "rationale": str
    }}],
    "rollback_plan": [{{"step": int, "action": str, "command": str}}],
    "monitoring_steps": [str],
    "post_incident_tasks": [str],
    "estimated_recovery_time": str,
    "confidence": float
}}
Root cause: {json.dumps(rc)[:2000]}
Rollback candidates: {json.dumps(deploy.get('rollback_candidates', []))}""", ctx)
        d = json.loads(raw)
        return AgentOutput(self.role,
            f"{len(d.get('immediate_actions',[]))} immediate actions. ETA: {d.get('estimated_recovery_time','unknown')}.",
            [], d, d.get("confidence", 0.78))


class IncidentOrchestrator:
    def __init__(self, incident_id, on_step=None):
        self.incident_id = incident_id
        self.on_step = on_step
        self.agents = [LogAnalystAgent(), DeployHistoryAgent(), RootCauseAgent(), RemediationAgent()]

    async def run(self, ctx):
        outputs = []
        total = len(self.agents)
        for i, agent in enumerate(self.agents):
            t0 = time.time()
            try: out = await agent.run(ctx)
            except Exception as e: out = AgentOutput(agent.role, f"Failed: {e}", [], {"error": str(e)}, 0.0)
            out.structured["_latency_ms"] = int((time.time()-t0)*1000)
            out.structured["_progress_pct"] = round((i+1)/total*100, 1)
            outputs.append(out)
            ctx[agent.role] = out.to_dict()
            if self.on_step: await self.on_step(out)
        return outputs
