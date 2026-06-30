"""Core data structures: Fact (a verified, source-bound statement), Candidate
(a fact under evaluation in the pipeline), and QAResult (the honest answer bundle).

A Fact's id is a deterministic uuid5 of (source_doc | text), so re-ingesting the
same document deduplicates naturally and the id doubles as the Qdrant point id.
"""
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _now():
    return datetime.now(timezone.utc).isoformat()


def fact_id(source_doc: str, text: str) -> str:
    return str(uuid.uuid5(_NS, f"{source_doc}|{text.strip()}"))


@dataclass
class Fact:
    text: str
    source_doc: str
    chunk_id: str
    page: Optional[int] = None
    paragraph: Optional[int] = None
    weight: float = 1.0          # accumulation weight (grows with co-usage)
    uses: int = 0                # how many answers have cited this fact
    created_ts: str = field(default_factory=_now)
    id: str = ""
    context: str = ""            # document scope/heading (Stufe 2): used for MATCHING only

    def __post_init__(self):
        if not self.id:
            self.id = fact_id(self.source_doc, self.text)

    @property
    def searchable(self) -> str:
        """Text used for embedding, the term-specificity filter and the guard: the fact
        prefixed with its document scope (heading), so an entity named only in the heading
        ("Pump Station P-12") still matches an entity question. The answer and the citation
        always use the clean `text` — the scope is a matching aid, not shown or invented."""
        return f"{self.context} — {self.text}" if self.context else self.text

    @property
    def source_label(self) -> str:
        if self.page is not None:
            return f"{self.source_doc}, p. {self.page}"
        if self.paragraph is not None:
            return f"{self.source_doc}, para. {self.paragraph}"
        return self.source_doc

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Candidate:
    fact: Fact
    score: float = 0.0           # raw cosine similarity from Qdrant
    term_score: float = 0.0      # term-specificity overlap (0..1), Stufe B
    final_score: float = 0.0     # hybrid score after accumulation re-rank
    on_target: bool = True       # passed the strict term-specificity filter (display/ranking)
    quantity_conflict: bool = False  # numeric near-neighbour (wrong number) -> hard veto
    status: str = "candidate"    # 'kept' | 'struck' | 'candidate'
    reason: str = ""
    covers: list = field(default_factory=list)  # sub-requirement indices this covers

    def to_dict(self) -> dict:
        return {
            "id": self.fact.id,
            "text": self.fact.text,
            "source": self.fact.source_label,
            "source_doc": self.fact.source_doc,
            "page": self.fact.page,
            "paragraph": self.fact.paragraph,
            "score": round(self.score, 4),
            "term_score": round(self.term_score, 4),
            "final_score": round(self.final_score, 4),
            "on_target": self.on_target,
            "status": self.status,
            "reason": self.reason,
            "weight": round(self.fact.weight, 4),
            "uses": self.fact.uses,
            "covers": self.covers,
        }


@dataclass
class QAResult:
    question: str
    answer: str = ""
    sub_requirements: list = field(default_factory=list)
    used_facts: list = field(default_factory=list)    # list[dict] (kept candidates)
    struck_facts: list = field(default_factory=list)  # list[dict] (struck/off-target)
    gaps: list = field(default_factory=list)          # uncovered sub-requirements
    sources: list = field(default_factory=list)       # distinct source labels cited
    dependency_tree: dict = field(default_factory=dict)  # node-link graph for the UI

    def to_dict(self) -> dict:
        return asdict(self)
