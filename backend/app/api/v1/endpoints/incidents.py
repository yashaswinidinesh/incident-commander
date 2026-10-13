"""
Incident Commander API endpoints — create incidents, stream agent progress, fetch results.
"""
import asyncio, json
from typing import AsyncGenerator
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.models.models import Incident, IncidentStep, Hypothesis, RemediationAction
from app.services.agents import IncidentOrchestrator, AgentOutput

router = APIRouter()

# In-memory SSE queues: incident_id -> list of queues
_sse_queues: dict[str, list[asyncio.Queue]] = {}


class CreateIncidentRequest(BaseModel):
    title: str = "Untitled Incident"
    severity: str = "p2"
    logs: str = ""
    deploy_history: list[dict] = []


async def _run_incident(incident_id: str, ctx: dict, db_url: str):
    """Background task: run 4 agents, persist results, push SSE."""
    from app.models.base import AsyncSessionLocal
    from app.models.models import Incident, IncidentStep, Hypothesis, RemediationAction

    async def on_step(out: AgentOutput):
        async with AsyncSessionLocal() as db:
            # Persist step
            step = IncidentStep(
                incident_id=incident_id,
                agent_role=out.role,
                status="done",
                output=out.structured,
                evidence=out.evidence,
                confidence=out.confidence,
                latency_ms=out.structured.get("_latency_ms", 0),
            )
            db.add(step)

            # Update incident progress
            inc = await db.get(Incident, incident_id)
            inc.progress_pct = out.structured.get("_progress_pct", 0.0)
            inc.current_agent = out.role

            # Persist hypotheses from root_cause agent
            if out.role == "root_cause":
                for h in out.structured.get("hypotheses", []):
                    db.add(Hypothesis(
                        incident_id=incident_id,
                        rank=h.get("rank", 0),
                        hypothesis=h.get("hypothesis", ""),
                        confidence=h.get("confidence", 0.0),
                        category=h.get("category", ""),
                        supporting_evidence=h.get("supporting_evidence", []),
                        contradicting_evidence=h.get("contradicting_evidence", []),
                    ))

            # Persist remediation actions
            if out.role == "remediation":
                for a in out.structured.get("immediate_actions", []):
                    db.add(RemediationAction(
                        incident_id=incident_id,
                        priority=a.get("priority", 0),
                        action=a.get("action", ""),
                        command=a.get("command", ""),
                        risk=a.get("risk", "low"),
                        requires_approval=a.get("requires_approval", False),
                        rationale=a.get("rationale", ""),
                    ))

            await db.commit()

        # Push SSE to all listeners
        event = json.dumps({
            "agent": out.role,
            "summary": out.summary,
            "confidence": out.confidence,
            "progress_pct": out.structured.get("_progress_pct", 0.0),
            "latency_ms": out.structured.get("_latency_ms", 0),
            "structured": out.structured,
            "evidence": out.evidence,
        })
        for q in _sse_queues.get(incident_id, []):
            await q.put(event)

    orchestrator = IncidentOrchestrator(incident_id, on_step=on_step)
    try:
        await orchestrator.run(ctx)
    except Exception as e:
        for q in _sse_queues.get(incident_id, []):
            await q.put(json.dumps({"error": str(e)}))
    finally:
        # Mark incident done
        async with AsyncSessionLocal() as db:
            inc = await db.get(Incident, incident_id)
            if inc:
                inc.status = "done"
                inc.progress_pct = 100.0
                inc.current_agent = ""
                await db.commit()
        # Signal done to all SSE clients
        for q in _sse_queues.get(incident_id, []):
            await q.put("__done__")


@router.post("", status_code=202)
async def create_incident(
    req: CreateIncidentRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    inc = Incident(
        title=req.title,
        severity=req.severity,
        status="running",
        progress_pct=0.0,
        current_agent="log_analyst",
    )
    db.add(inc)
    await db.commit()
    await db.refresh(inc)

    ctx = {
        "logs": req.logs,
        "deploy_history": req.deploy_history,
        "title": req.title,
        "severity": req.severity,
    }
    _sse_queues[inc.id] = []
    background_tasks.add_task(_run_incident, inc.id, ctx, "")
    return {"incident_id": inc.id, "status": "running"}


@router.get("/{incident_id}/stream")
async def stream_incident(incident_id: str, db: AsyncSession = Depends(get_db)):
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found")

    q: asyncio.Queue = asyncio.Queue()
    _sse_queues.setdefault(incident_id, []).append(q)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                data = await asyncio.wait_for(q.get(), timeout=60)
                if data == "__done__":
                    yield "event: done\ndata: {}\n\n"
                    break
                yield f"data: {data}\n\n"
        except asyncio.TimeoutError:
            yield "event: timeout\ndata: {}\n\n"
        finally:
            try:
                _sse_queues.get(incident_id, []).remove(q)
            except ValueError:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("")
async def list_incidents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Incident).order_by(Incident.created_at.desc()).limit(50)
    )
    incidents = result.scalars().all()
    return [{"id": i.id, "title": i.title, "severity": i.severity,
             "status": i.status, "progress_pct": i.progress_pct,
             "created_at": i.created_at.isoformat()} for i in incidents]


@router.get("/{incident_id}")
async def get_incident(incident_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Incident)
        .options(
            selectinload(Incident.steps),
            selectinload(Incident.hypotheses),
            selectinload(Incident.actions),
        )
        .where(Incident.id == incident_id)
    )
    inc = result.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")

    return {
        "id": inc.id,
        "title": inc.title,
        "severity": inc.severity,
        "status": inc.status,
        "progress_pct": inc.progress_pct,
        "current_agent": inc.current_agent,
        "created_at": inc.created_at.isoformat(),
        "steps": [{"agent_role": s.agent_role, "status": s.status,
                   "summary": s.output.get("summary", ""), "confidence": s.confidence,
                   "latency_ms": s.latency_ms, "output": s.output, "evidence": s.evidence}
                  for s in inc.steps],
        "hypotheses": [{"rank": h.rank, "hypothesis": h.hypothesis,
                        "confidence": h.confidence, "category": h.category,
                        "supporting_evidence": h.supporting_evidence,
                        "contradicting_evidence": h.contradicting_evidence}
                       for h in sorted(inc.hypotheses, key=lambda x: x.rank)],
        "actions": [{"priority": a.priority, "action": a.action, "command": a.command,
                     "risk": a.risk, "requires_approval": a.requires_approval,
                     "rationale": a.rationale, "status": a.status, "id": a.id}
                    for a in sorted(inc.actions, key=lambda x: x.priority)],
    }


@router.patch("/{incident_id}/actions/{action_id}")
async def update_action(incident_id: str, action_id: str,
                        body: dict, db: AsyncSession = Depends(get_db)):
    action = await db.get(RemediationAction, action_id)
    if not action or action.incident_id != incident_id:
        raise HTTPException(404, "Action not found")
    if "status" in body and body["status"] in ("pending", "approved", "done"):
        action.status = body["status"]
    await db.commit()
    return {"id": action_id, "status": action.status}
