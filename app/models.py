"""Typed handoffs. Every artifact passed between agents is one of these Pydantic models.

LLM-facing schemas are kept flat and small so open-weight models can fill them reliably.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Provenance(str, Enum):
    founder = "founder"
    web = "web"
    agent = "agent"


class Label(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    ASSUMPTION = "ASSUMPTION"


class Verdict(str, Enum):
    GO = "GO"
    REPEAT = "REPEAT"
    PIVOT_BACK = "PIVOT_BACK"
    PARK = "PARK"
    STOP = "STOP"


ClaimType = Literal["demand_signal", "paying_competitor", "competitor", "trend", "market_size", "compliance", "other"]


# ---------------------------------------------------------------- Phase 1 ---------------
class FounderInput(BaseModel):
    """What the founder typed. Only intake ever sees this raw text."""
    idea: str
    skills: str = ""
    budget: str = ""
    time: str = ""
    target_market: str = ""
    values: str = ""


class Brief(BaseModel):
    """Parsed brief; later calls get this, never the raw founder text."""
    idea: str
    product_type: str = Field(description="kind of digital product, e.g. 'guide/template pack'")
    skills: list[str] = []
    budget_usd: Optional[float] = None
    hours_per_week: Optional[float] = None
    weeks_available: Optional[float] = None
    target_market: str = ""
    values: list[str] = []
    missing_info: list[str] = Field(default=[], description="facts that are missing; do not guess them")
    questions_for_founder: list[str] = []


class SearchTerms(BaseModel):
    """Keywords only. Search queries are built from these in code (app/services/search/queries.py)."""
    problem: str = Field(description="the buyer's problem in 2-5 plain words, e.g. 'late invoice payments'")
    audience: str = Field(description="the buyer in 1-3 words, e.g. 'freelance designers'")
    product_type: str = Field(description="what is sold in 1-3 words, e.g. 'invoice templates'")
    synonyms: list[str] = Field(default_factory=list, max_length=3,
                                description="up to 3 other short ways buyers name the problem")


class PlanEstimate(BaseModel):
    hours_low: float
    hours_high: float
    cost_low_usd: float
    cost_high_usd: float
    required_skills: list[str]
    search_terms: SearchTerms
    adjustment_reason: Optional[str] = Field(default=None, description=(
        "Only if you moved a range away from the given baseline: one sentence saying why. Otherwise null."))
    # Filled in code after the model replies (hidden from the model's schema): baseline used and clamping.
    baseline_key: SkipJsonSchema[Optional[str]] = None
    baseline: SkipJsonSchema[Optional[dict[str, Any]]] = None
    model_estimate: SkipJsonSchema[Optional[dict[str, float]]] = None
    clamped: SkipJsonSchema[bool] = False


class Scores(BaseModel):
    demand: int = Field(ge=1, le=5)
    founder_fit: int = Field(ge=1, le=5)
    regulatory_burden: int = Field(ge=1, le=5, description="5 = heavy regulation")
    effort: int = Field(ge=1, le=5, description="5 = very hard to build")


class IdeaVariant(BaseModel):
    name: str
    one_liner: str
    buyer: str
    problem: str
    scores: Scores
    regulatory_claim_ids: list[str] = []


class TheoryOfValue(BaseModel):
    who: str
    problem: str
    why_now: str
    why_us: str


class IdeaMatrix(BaseModel):
    theory_of_value: TheoryOfValue
    variants: list[IdeaVariant] = Field(min_length=3, max_length=5)


class ProblemQuote(BaseModel):
    quote: str
    date: Optional[str] = None


class PageExtract(BaseModel):
    page_kind: Literal["product", "forum", "article", "other"]
    product_name: Optional[str] = None
    price_text: Optional[str] = None
    has_public_price: bool = False
    features: list[str] = []
    problem_statements: list[ProblemQuote] = []
    audience: Optional[str] = None


class ClaimDraft(BaseModel):
    text: str
    type: ClaimType
    source_url: str
    source_quote: str = Field(description="exact words copied from the source text")


class ClaimList(BaseModel):
    claims: list[ClaimDraft] = []


class CheckResult(BaseModel):
    label: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    reason: str


class Claim(BaseModel):
    id: str
    run_id: str
    text: str
    type: str
    label: Label
    source_url: Optional[str] = None
    source_quote: Optional[str] = None
    retrieved_at: Optional[str] = None
    checked_by_model: Optional[str] = None
    checked_by_family: Optional[str] = None
    writer_family: Optional[str] = None
    provenance: Provenance = Provenance.agent
    artifact_id: Optional[str] = None
    note: Optional[str] = None


class CompetitorRow(BaseModel):
    name: str
    url: str
    price_text: Optional[str] = None
    is_direct: bool = Field(description="same buyer, same job, same channel")
    direct_reason: str = ""


class CompetitorTable(BaseModel):
    rows: list[CompetitorRow] = []


class ComplianceFlag(BaseModel):
    issue: str
    blocking: bool
    reason: str


class ComplianceQuick(BaseModel):
    flags: list[ComplianceFlag] = []
    regulatory_burden: int = Field(ge=1, le=5)


class InterviewScript(BaseModel):
    goal: str
    questions: list[str] = Field(min_length=5)
    avoid: list[str] = []


class MarketSummary(BaseModel):
    summary: str = Field(description="cite claim ids like [C3]; anything without an id is an ASSUMPTION")
    segments: list[str] = []


class GateExplanation(BaseModel):
    text: str


class DevilsAdvocate(BaseModel):
    bull_case: str
    bear_case: str


# ---------------------------------------------------------------- Phase 2 ---------------
class CanvasItem(BaseModel):
    text: str
    claim_id: Optional[str] = Field(default=None, description="ledger claim id that supports this, else null")


class Assumption(BaseModel):
    text: str
    impact: int = Field(ge=1, le=5)
    uncertainty: int = Field(ge=1, le=5)


class LeanCanvas(BaseModel):
    problem: list[CanvasItem]
    customer_segments: list[CanvasItem]
    unique_value_proposition: list[CanvasItem]
    solution: list[CanvasItem]
    channels: list[CanvasItem]
    revenue_streams: list[CanvasItem]
    cost_structure: list[CanvasItem]
    key_metrics: list[CanvasItem]
    unfair_advantage: list[CanvasItem]
    assumptions: list[Assumption] = Field(min_length=3)


class ExperimentPlan(BaseModel):
    hypothesis: str
    assumption_tested: str
    metric: str = "waitlist sign-ups"
    signups_threshold: int = Field(ge=1)
    min_visitors: int = Field(ge=1)
    window_days: int = Field(ge=1, le=60)
    threshold_source: Literal["benchmark", "ASSUMPTION"]
    benchmark_claim_id: Optional[str] = None
    rationale: str
    change_our_mind: str


class FAQ(BaseModel):
    q: str
    a: str


class LandingCopy(BaseModel):
    headline: str
    subheadline: str
    bullets: list[str] = Field(min_length=2, max_length=6)
    cta: str
    faq: list[FAQ] = []


class InterviewInsights(BaseModel):
    patterns: list[str]
    quotes: list[str]
    open_questions: list[str]


# ---------------------------------------------------------------- Phase 3 ---------------
class PRD(BaseModel):
    product_title: str
    audience: str
    problem: str
    outcomes: list[str]
    required_sections: list[str] = Field(min_length=3, max_length=8)
    out_of_scope: list[str] = []


class GuideSection(BaseModel):
    heading: str
    body_markdown: str


class GuideTemplate(BaseModel):
    name: str
    body_markdown: str


class GuidePack(BaseModel):
    title: str
    intro: str
    sections: list[GuideSection] = Field(min_length=3)
    templates: list[GuideTemplate] = []


class TestSpec(BaseModel):
    __test__ = False  # not a pytest class
    required_headings: list[str]
    min_sections: int = Field(ge=1)
    min_words_per_section: int = Field(ge=10)
    forbidden_phrases: list[str] = []
    max_spelling_error_rate: float = Field(default=0.08, ge=0.0, le=0.5)


class UserDocs(BaseModel):
    markdown: str


# ---------------------------------------------------------------- Phase 4 ---------------
class PriceTier(BaseModel):
    name: str
    price_usd: float = Field(ge=0)
    includes: list[str]


class PricingSheet(BaseModel):
    tiers: list[PriceTier] = Field(min_length=1, max_length=3)
    rationale: str
    competitor_claim_ids: list[str] = []


class PolicyDrafts(BaseModel):
    terms_md: str
    privacy_md: str
    refund_md: str


class ChecklistItem(BaseModel):
    item: str
    source_id: str = Field(description="id from the official sources list")
    applies: bool
    note: str


class ComplianceChecklist(BaseModel):
    items: list[ChecklistItem] = Field(min_length=3)


# ---------------------------------------------------------------- Phase 5/6 -------------
class StorePage(BaseModel):
    title: str
    tagline: str
    description: str
    bullets: list[str]
    faq: list[FAQ] = []


class LaunchPost(BaseModel):
    channel: str
    text: str


class LaunchPosts(BaseModel):
    posts: list[LaunchPost] = Field(min_length=1, max_length=4)


class SupportReply(BaseModel):
    ticket_id: str
    draft: str


class SupportDrafts(BaseModel):
    replies: list[SupportReply]


class MetricsReading(BaseModel):
    observations: list[str]
    risks: list[str]


class MemoBody(BaseModel):
    body: str


class Persona(BaseModel):
    name: str
    situation: str
    attitude: str


class Personas(BaseModel):
    personas: list[Persona] = Field(min_length=3, max_length=3)


class PersonaReply(BaseModel):
    reply: str


class CoachFeedback(BaseModel):
    leading: bool
    hypothetical: bool
    tip: str


class PolicyDecision(BaseModel):
    decision: Literal["ALLOW", "REFUSE"]
    reason: str


class QueryList(BaseModel):
    queries: list[str]
