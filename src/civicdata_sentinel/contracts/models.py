"""Strict proposal schema, independent from production configuration and approvals."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..config import Check, ContractModel, Dataset
from .evidence import Document


class Citation(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class Rule(ContractModel):
    check: Check
    basis: Literal["documented", "inferred", "statistical"]
    method: Literal["deterministic", "sample_profile", "llm", "reviewer"]
    evidence: list[Citation] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    limitations: str = Field(min_length=1)
    uncertain: bool = True
    conflict: bool = False
    approval: Literal["pending"] = "pending"

    @model_validator(mode="after")
    def safe_subset(self):
        if self.check.kind not in {"completeness", "unique", "domain", "numeric", "freshness"}:
            raise ValueError("Proposal rules support only the declarative safe subset")
        if self.basis == "documented" and not self.evidence:
            raise ValueError("Documented rules require citations")
        if self.method == "llm" and (self.basis != "inferred" or not self.uncertain):
            raise ValueError("LLM proposals remain uncertain inferences until human review")
        return self


class Proposal(ContractModel):
    format_version: Literal[1] = 1
    created_at: str
    base_yaml: str
    sample_origin: str
    sample_captured_at: str
    fields: list[str] = Field(min_length=1, max_length=1000)
    rows: list[dict[str, str]] = Field(max_length=10000)
    documents: list[Document] = Field(max_length=20)
    rules: list[Rule] = Field(default_factory=list, max_length=500)
    abstentions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def linked(self):
        import yaml

        Dataset.model_validate(yaml.safe_load(self.base_yaml))
        ids = [rule.check.id for rule in self.rules]
        if len(ids) != len(set(ids)) or len(self.fields) != len(set(self.fields)):
            raise ValueError("Rule IDs and field names must be distinct")
        if any(set(row) != set(self.fields) for row in self.rows):
            raise ValueError("Sample rows must have exactly the declared fields")
        docs = {doc.id: doc for doc in self.documents}
        for rule in self.rules:
            for cite in rule.evidence:
                doc = docs.get(cite.document_id)
                if not doc or cite.page > len(doc.pages) or cite.quote not in doc.pages[cite.page - 1]:
                    raise ValueError("Citation is absent from the retained document/page")
        return self
