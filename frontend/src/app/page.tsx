'use client'
import { useState, useRef } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const DEMO_LOGS = `2024-01-15T14:32:01Z ERROR [payment-service] Connection pool exhausted: max=50 current=50
2024-01-15T14:32:03Z ERROR [payment-service] Timeout connecting to postgres://db-primary:5432/payments after 30s
2024-01-15T14:32:05Z WARN  [api-gateway] Circuit breaker OPEN for payment-service (failures=10)
2024-01-15T14:32:07Z ERROR [order-service] Failed to confirm order #8821: upstream payment-service unavailable
2024-01-15T14:32:10Z ERROR [payment-service] OOMKilled: container memory limit 512Mi exceeded
2024-01-15T14:32:12Z INFO  [k8s] Restarting pod payment-service-7d9f8b6c5-xk2p1
2024-01-15T14:32:45Z ERROR [payment-service] CrashLoopBackOff: restart count=5
2024-01-15T14:33:00Z ERROR [alertmanager] P1 alert: payment-service down, 0/3 pods healthy`

const DEMO_DEPLOYS = JSON.stringify([
  { service: "payment-service", version: "v2.4.1", time: "2024-01-15T13:55:00Z", author: "jenkins-ci", changes: "Increase connection pool size, add retry logic" },
  { service: "db-proxy", version: "v1.2.0", time: "2024-01-15T12:30:00Z", author: "alice@company.com", changes: "Upgrade pgbouncer 1.18→1.21" },
  { service: "api-gateway", version: "v3.1.0", time: "2024-01-14T16:00:00Z", author: "bob@company.com", changes: "Add circuit breaker for payment-service" },
], null, 2)

const AGENT_META: Record<string, { label: string; color: string; icon: string }> = {
  log_analyst:    { label: 'Log Analyst',    color: 'text-blue-400',   icon: '🔍' },
  deploy_history: { label: 'Deploy History', color: 'text-yellow-400', icon: '🚀' },
  root_cause:     { label: 'Root Cause',     color: 'text-purple-400', icon: '🧠' },
  remediation:    { label: 'Remediation',    color: 'text-green-400',  icon: '🔧' },
}

const SEVERITY_COLORS: Record<string, string> = {
  p1: 'bg-red-600 text-white', p2: 'bg-orange-500 text-white',
  p3: 'bg-yellow-500 text-black', p4: 'bg-blue-500 text-white',
}

const RISK_COLORS: Record<string, string> = {
  low: 'text-green-400', medium: 'text-yellow-400', high: 'text-red-400',
}

interface StepEvent {
  agent: string; summary: string; confidence: number;
  progress_pct: number; latency_ms: number;
  structured: Record<string, unknown>; evidence: unknown[];
}

interface Hypothesis {
  rank: number; hypothesis: string; confidence: number; category: string;
  supporting_evidence: string[]; contradicting_evidence: string[];
}

interface Action {
  id: string; priority: number; action: string; command: string;
  risk: string; requires_approval: boolean; rationale: string; status: string;
}

export default function Home() {
  const [title, setTitle] = useState('Payment Service P1 — Connection Pool Exhausted')
  const [severity, setSeverity] = useState('p1')
  const [logs, setLogs] = useState(DEMO_LOGS)
  const [deploys, setDeploys] = useState(DEMO_DEPLOYS)

  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [steps, setSteps] = useState<StepEvent[]>([])
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([])
  const [actions, setActions] = useState<Action[]>([])
  const [actionStatuses, setActionStatuses] = useState<Record<string, string>>({})
  const [progress, setProgress] = useState(0)
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const esRef = useRef<EventSource | null>(null)

  async function runIncident() {
    setRunning(true); setDone(false); setSteps([]); setHypotheses([]); setActions([]); setProgress(0)
    let deployList: unknown[] = []
    try { deployList = JSON.parse(deploys) } catch { deployList = [] }

    const res = await fetch(`${API}/api/v1/incidents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, severity, logs, deploy_history: deployList }),
    })
    const { incident_id } = await res.json()
    setIncidentId(incident_id)

    if (esRef.current) esRef.current.close()
    const es = new EventSource(`${API}/api/v1/incidents/${incident_id}/stream`)
    esRef.current = es

    es.onmessage = (e) => {
      const data: StepEvent = JSON.parse(e.data)
      setSteps(prev => [...prev, data])
      setProgress(data.progress_pct)
      if (data.agent === 'root_cause') {
        const s = data.structured as Record<string, unknown>
        setHypotheses((s.hypotheses as Hypothesis[]) || [])
      }
      if (data.agent === 'remediation') {
        const s = data.structured as Record<string, unknown>
        const acts = (s.immediate_actions as Action[]) || []
        setActions(acts.map((a, i) => ({ ...a, id: String(i), status: 'pending' })))
      }
    }
    es.addEventListener('done', () => { es.close(); setRunning(false); setDone(true) })
    es.onerror = () => { es.close(); setRunning(false); setDone(true) }
  }

  async function approveAction(idx: number) {
    if (!incidentId) return
    // Optimistically update status
    setActionStatuses(prev => ({ ...prev, [idx]: 'approved' }))
  }

  const mostLikelyCause = steps.find(s => s.agent === 'root_cause')
    ?.structured?.most_likely_cause as string | undefined

  return (
    <div className="min-h-screen" style={{ background: '#0d1117', color: '#e6edf3' }}>
      {/* Header */}
      <header className="border-b" style={{ borderColor: '#30363d', background: '#161b22' }}>
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <span className="text-2xl">🚨</span>
          <div>
            <h1 className="text-xl font-bold text-white">Incident Commander</h1>
            <p className="text-xs" style={{ color: '#8b949e' }}>Multi-Agent Incident Response · Logs → Root Cause → Remediation</p>
          </div>
          {running && (
            <div className="ml-auto flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-sm text-red-400">LIVE INCIDENT</span>
            </div>
          )}
          {done && <span className="ml-auto text-sm text-green-400">✓ Analysis complete</span>}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Input Panel */}
        <div className="lg:col-span-1 space-y-4">
          <div className="rounded-lg p-4 space-y-3" style={{ background: '#161b22', border: '1px solid #30363d' }}>
            <h2 className="font-semibold text-sm uppercase tracking-wide" style={{ color: '#8b949e' }}>Incident Details</h2>

            <div>
              <label className="text-xs mb-1 block" style={{ color: '#8b949e' }}>Title</label>
              <input value={title} onChange={e => setTitle(e.target.value)}
                className="w-full px-3 py-2 rounded text-sm text-white"
                style={{ background: '#0d1117', border: '1px solid #30363d' }} />
            </div>

            <div>
              <label className="text-xs mb-1 block" style={{ color: '#8b949e' }}>Severity</label>
              <select value={severity} onChange={e => setSeverity(e.target.value)}
                className="w-full px-3 py-2 rounded text-sm text-white"
                style={{ background: '#0d1117', border: '1px solid #30363d' }}>
                {['p1','p2','p3','p4'].map(s => (
                  <option key={s} value={s}>{s.toUpperCase()}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs mb-1 block" style={{ color: '#8b949e' }}>Logs</label>
              <textarea rows={8} value={logs} onChange={e => setLogs(e.target.value)}
                className="w-full px-3 py-2 rounded text-xs font-mono text-white resize-none"
                style={{ background: '#0d1117', border: '1px solid #30363d' }} />
            </div>

            <div>
              <label className="text-xs mb-1 block" style={{ color: '#8b949e' }}>Deploy History (JSON array)</label>
              <textarea rows={6} value={deploys} onChange={e => setDeploys(e.target.value)}
                className="w-full px-3 py-2 rounded text-xs font-mono text-white resize-none"
                style={{ background: '#0d1117', border: '1px solid #30363d' }} />
            </div>

            <button onClick={runIncident} disabled={running}
              className="w-full py-2 px-4 rounded font-semibold text-sm transition-all"
              style={{ background: running ? '#21262d' : '#da3633', color: running ? '#8b949e' : '#fff',
                       cursor: running ? 'not-allowed' : 'pointer' }}>
              {running ? `Analyzing… ${Math.round(progress)}%` : '🚨 Run Incident Analysis'}
            </button>
          </div>

          {/* Progress bar */}
          {(running || done) && (
            <div className="rounded-lg p-4" style={{ background: '#161b22', border: '1px solid #30363d' }}>
              <div className="flex justify-between text-xs mb-2" style={{ color: '#8b949e' }}>
                <span>Pipeline Progress</span><span>{Math.round(progress)}%</span>
              </div>
              <div className="h-2 rounded-full" style={{ background: '#21262d' }}>
                <div className="h-2 rounded-full transition-all duration-500"
                     style={{ width: `${progress}%`, background: done ? '#238636' : '#da3633' }} />
              </div>
              <div className="mt-3 space-y-2">
                {Object.entries(AGENT_META).map(([key, meta]) => {
                  const step = steps.find(s => s.agent === key)
                  return (
                    <div key={key} className="flex items-center gap-2 text-xs">
                      <span>{meta.icon}</span>
                      <span className={step ? meta.color : 'text-gray-600'}>{meta.label}</span>
                      {step && <span className="ml-auto" style={{ color: '#8b949e' }}>{(step.confidence*100).toFixed(0)}%</span>}
                      {!step && running && steps.length === Object.keys(AGENT_META).indexOf(key) &&
                        <span className="ml-auto text-yellow-400 animate-pulse">running</span>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right: Results */}
        <div className="lg:col-span-2 space-y-4">
          {/* Agent Timeline */}
          {steps.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: '#161b22', border: '1px solid #30363d' }}>
              <h2 className="font-semibold text-sm mb-3 uppercase tracking-wide" style={{ color: '#8b949e' }}>Agent Pipeline</h2>
              <div className="space-y-2">
                {steps.map((step, i) => {
                  const meta = AGENT_META[step.agent] || { label: step.agent, color: 'text-gray-400', icon: '•' }
                  return (
                    <div key={i}>
                      <div className="flex items-center gap-3 p-3 rounded cursor-pointer hover:bg-opacity-80"
                           style={{ background: '#0d1117', border: '1px solid #30363d' }}
                           onClick={() => setActiveStep(activeStep === i ? null : i)}>
                        <span className="text-lg">{meta.icon}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`font-medium text-sm ${meta.color}`}>{meta.label}</span>
                            <span className="px-2 py-0.5 rounded text-xs" style={{ background: '#238636', color: '#7ee787' }}>done</span>
                          </div>
                          <p className="text-xs mt-0.5 truncate" style={{ color: '#8b949e' }}>{step.summary}</p>
                        </div>
                        <div className="text-right shrink-0">
                          <div className="text-xs font-mono text-white">{(step.confidence*100).toFixed(0)}%</div>
                          <div className="text-xs" style={{ color: '#8b949e' }}>{step.latency_ms}ms</div>
                        </div>
                        <span className="text-xs" style={{ color: '#8b949e' }}>{activeStep === i ? '▲' : '▼'}</span>
                      </div>
                      {activeStep === i && (
                        <div className="mx-3 p-3 rounded-b text-xs font-mono overflow-auto max-h-48"
                             style={{ background: '#0a0d12', border: '1px solid #21262d', borderTop: 'none', color: '#7ee787' }}>
                          {JSON.stringify(step.structured, null, 2)}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Root Cause Summary */}
          {mostLikelyCause && (
            <div className="rounded-lg p-4" style={{ background: '#161b22', border: '1px solid #da3633' }}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-red-400 font-semibold text-sm uppercase tracking-wide">🎯 Most Likely Root Cause</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_COLORS[severity] || 'bg-gray-700 text-white'}`}>{severity.toUpperCase()}</span>
              </div>
              <p className="text-white text-sm">{mostLikelyCause}</p>
            </div>
          )}

          {/* Hypotheses */}
          {hypotheses.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: '#161b22', border: '1px solid #30363d' }}>
              <h2 className="font-semibold text-sm mb-3 uppercase tracking-wide" style={{ color: '#8b949e' }}>Root Cause Hypotheses</h2>
              <div className="space-y-3">
                {hypotheses.map((h, i) => (
                  <div key={i} className="p-3 rounded" style={{ background: '#0d1117', border: '1px solid #21262d' }}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-bold text-sm">#{h.rank}</span>
                        <span className="px-2 py-0.5 rounded text-xs" style={{ background: '#1f2937', color: '#a78bfa' }}>{h.category}</span>
                      </div>
                      <span className="text-sm font-mono" style={{ color: h.confidence > 0.7 ? '#f85149' : h.confidence > 0.4 ? '#d29922' : '#8b949e' }}>
                        {(h.confidence*100).toFixed(0)}% conf
                      </span>
                    </div>
                    <p className="text-sm text-white mb-2">{h.hypothesis}</p>
                    {h.supporting_evidence.length > 0 && (
                      <div className="mb-1">
                        <span className="text-xs text-green-400">✓ Supporting: </span>
                        <span className="text-xs" style={{ color: '#8b949e' }}>{h.supporting_evidence.join(' · ')}</span>
                      </div>
                    )}
                    {h.contradicting_evidence.length > 0 && (
                      <div>
                        <span className="text-xs text-red-400">✗ Contradicting: </span>
                        <span className="text-xs" style={{ color: '#8b949e' }}>{h.contradicting_evidence.join(' · ')}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Remediation Actions */}
          {actions.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: '#161b22', border: '1px solid #30363d' }}>
              <h2 className="font-semibold text-sm mb-3 uppercase tracking-wide" style={{ color: '#8b949e' }}>Remediation Actions</h2>
              <div className="space-y-3">
                {actions.map((action, i) => {
                  const status = actionStatuses[i] || action.status || 'pending'
                  return (
                    <div key={i} className="p-3 rounded" style={{ background: '#0d1117', border: '1px solid #21262d' }}>
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-white font-bold text-sm">P{action.priority}</span>
                          <span className={`text-xs font-medium ${RISK_COLORS[action.risk] || 'text-gray-400'}`}>
                            {action.risk?.toUpperCase()} RISK
                          </span>
                          {action.requires_approval && (
                            <span className="px-2 py-0.5 rounded text-xs" style={{ background: '#5a3e1b', color: '#d29922' }}>⚠ Approval Required</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {status === 'approved' ? (
                            <span className="text-xs text-green-400">✓ Approved</span>
                          ) : (
                            <button onClick={() => approveAction(i)}
                              className="px-3 py-1 rounded text-xs font-medium"
                              style={{ background: '#238636', color: '#fff' }}>
                              Approve
                            </button>
                          )}
                        </div>
                      </div>
                      <p className="text-sm text-white mb-2">{action.action}</p>
                      {action.command && (
                        <div className="p-2 rounded font-mono text-xs mb-2" style={{ background: '#0a0d12', color: '#7ee787' }}>
                          $ {action.command}
                        </div>
                      )}
                      {action.rationale && (
                        <p className="text-xs" style={{ color: '#8b949e' }}>{action.rationale}</p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Empty state */}
          {!running && !done && (
            <div className="rounded-lg p-12 text-center" style={{ background: '#161b22', border: '1px solid #30363d' }}>
              <div className="text-5xl mb-4">🚨</div>
              <p className="text-white font-medium mb-1">Ready for Incident Response</p>
              <p className="text-sm" style={{ color: '#8b949e' }}>
                Paste logs and deploy history, then click Run to start the 4-agent analysis pipeline.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
