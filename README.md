# Incident Commander 🚨

> Multi-Agent Incident Response: paste logs + deploy history → 4 specialized agents chain analysis → ranked root-cause hypotheses + executable remediation plan.

## Agents

| # | Agent | Output |
|---|-------|--------|
| 1 | **Log Analyst** | Error patterns, affected services, anomaly timeline |
| 2 | **Deploy History** | Suspicious deploys, correlation with incident, rollback candidates |
| 3 | **Root Cause** | Ranked hypotheses with supporting/contradicting evidence + confidence scores |
| 4 | **Remediation** | Immediate actions with risk levels, approval gates, runbook commands |

## Guarantees

- **Evidence-based** — every hypothesis links to specific log lines or deploy records
- **Hypothesis vs confirmed** — `confidence` scores (0–1) distinguish correlation from causation
- **Approval gates** — high-risk actions flagged with `requires_approval: true`
- **Mock mode** — works without an OpenAI API key for demo purposes

## Quick Start

```bash
git clone https://github.com/yashaswinidinesh/incident-commander
cd incident-commander

# Optional: add your OpenAI key for real analysis
echo "OPENAI_API_KEY=sk-..." > .env

docker compose up --build
```

Open **http://localhost:3000**, paste logs, click **Run Incident Analysis**.

## Local Dev

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install && npm run dev
```

## API

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/incidents` | Create incident + start analysis pipeline |
| `GET /api/v1/incidents` | List recent incidents |
| `GET /api/v1/incidents/{id}` | Full detail: steps, hypotheses, actions |
| `GET /api/v1/incidents/{id}/stream` | SSE stream of live agent events |
| `PATCH /api/v1/incidents/{id}/actions/{aid}` | Approve / mark done a remediation action |

### Example Request

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Payment Service P1 - Connection Pool Exhausted",
    "severity": "p1",
    "logs": "2024-01-15T14:32:01Z ERROR [payment-service] Connection pool exhausted...",
    "deploy_history": [
      {"service": "payment-service", "version": "v2.4.1", "time": "2024-01-15T13:55:00Z", "author": "jenkins-ci"}
    ]
  }'
```

## Stack

FastAPI · SQLAlchemy async · PostgreSQL · Next.js 14 · Tailwind · Docker Compose · GitHub Actions

## Hosted Deployment

Deploy the API and database on Render using the root `render.yaml` Blueprint, then set `NEXT_PUBLIC_API_URL` in the Vercel project to `https://<render-api-host>`. Redeploy the frontend after setting the variable. Without this value, the analysis button stays disabled outside local development.

The Blueprint reuses the existing `research-proto-agent-db` Render PostgreSQL instance; Incident Commander stores its data in separate tables. This avoids creating another database, but both apps share its lifecycle and 30-day free-tier expiry. Leave `OPENAI_API_KEY` unset to use mock analysis.

## Author

**Yashaswini Dinesh** · [linkedin.com/in/yashaswini-dinesh-roopa](https://linkedin.com/in/yashaswini-dinesh-roopa)
