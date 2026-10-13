from sqlalchemy import String, Text, JSON, Float, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, new_uuid

class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[str] = mapped_column(String, default="unknown")  # p1|p2|p3|p4
    status: Mapped[str] = mapped_column(String, default="pending")
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    current_agent: Mapped[str] = mapped_column(String, default="")
    steps: Mapped[list["IncidentStep"]] = relationship(back_populates="incident", order_by="IncidentStep.created_at")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="incident")
    actions: Mapped[list["RemediationAction"]] = relationship(back_populates="incident")

class IncidentStep(Base, TimestampMixin):
    __tablename__ = "incident_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    agent_role: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    output: Mapped[dict] = mapped_column(JSON, default={})
    evidence: Mapped[list] = mapped_column(JSON, default=[])
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    incident: Mapped["Incident"] = relationship(back_populates="steps")

class Hypothesis(Base, TimestampMixin):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    hypothesis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String, default="")
    supporting_evidence: Mapped[list] = mapped_column(JSON, default=[])
    contradicting_evidence: Mapped[list] = mapped_column(JSON, default=[])
    incident: Mapped["Incident"] = relationship(back_populates="hypotheses")

class RemediationAction(Base, TimestampMixin):
    __tablename__ = "remediation_actions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[str] = mapped_column(Text)
    command: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String, default="low")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|approved|done
    incident: Mapped["Incident"] = relationship(back_populates="actions")
