from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectoryRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


class InvestigationRequest(StrictModel):
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    logs: str = Field(default="", max_length=100_000)


class DiagnosticCheck(StrictModel):
    tool: Literal["search", "python_syntax", "config_keys"]
    path: str = Field(min_length=1, max_length=300)
    query: str = Field(default="", max_length=200)


class Hypothesis(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    reasoning: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[str] = Field(min_length=1, max_length=20)
    contradicting_evidence: list[str] = Field(default_factory=list, max_length=20)
    diagnostic_checks: list[DiagnosticCheck] = Field(default_factory=list, max_length=4)


class Analysis(StrictModel):
    summary: str = Field(min_length=1, max_length=3000)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=8)


class Edit(StrictModel):
    path: str = Field(min_length=1, max_length=300)
    old: str = Field(min_length=1, max_length=20000)
    new: str = Field(max_length=20000)


class PatchProposal(StrictModel):
    explanation: str = Field(min_length=1, max_length=3000)
    hypothesis_ids: list[str] = Field(min_length=1, max_length=8)
    edits: list[Edit] = Field(min_length=1, max_length=30)
