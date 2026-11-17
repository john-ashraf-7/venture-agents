# Venture Builder

An open-source team of AI agents that takes a founder's brief toward a validated, sellable **digital** product through six gated phases, and that recommends **STOP** when the evidence is weak. Gate verdicts are computed by plain code against rules locked before the evidence is gathered; the founder makes every final call; nothing is published, sent or spent without founder approval in the Outbox. Runs entirely on local open-weight models (gpt-oss:20b + qwen3:8b via Ollama). License: Apache-2.0.

## Quickstart

```bash
docker compose up
```

Then open **http://localhost:8000**, paste a founder brief (or click an example brief) and press **Start run**. Progress streams live; the run stops at each gate for your decision.

- Needs Docker Compose v2 and an NVIDIA GPU with the NVIDIA Container Toolkit (target: RTX 3090, 24 GB). The first start pulls ~19 GB of models (`ollama-pull` init service); the app starts when they are ready.
- One-shot setup with health checks, smoke tests and model warm-up: `bash scripts/rtx_quickstart.sh` (Linux/WSL2) or `scripts\rtx_quickstart.ps1` (Windows).
- No GPU: `PULL_MODELS="qwen3:4b nomic-embed-text" docker compose -f docker-compose.yml -f docker-compose.cpu.yml up` and set `ROLE_*` overrides in `.env` (slow).
- Smoke tests (no GPU needed, STUBBED LLM): `docker compose run --rm --no-deps app python -m pytest -q`
- Headless timed run: `docker compose exec app python -m app.cli run --brief evals/briefs/invoice_templates.json`
- Optional: put your own free Tavily key in `.env` (`TAVILY_API_KEY=...`, see `.env.example`) to use Tavily search; without it the app uses self-hosted SearXNG and needs no key.

## What works and what is mocked

| Step | Status | Notes |
|---|---|---|
| Intake (parse brief, ask for missing info, block excluded product types) | **Working** | `app/agents/intake.py`, `app/services/guard.py` |
| Desk-gate rule locked (sha256 + timestamp) before research | **Working** | `app/gates.py` `lock_rule` |
| Capped web search (self-hosted SearXNG) with on-disk cache fallback | **Working** | labeled "cached search from <time>" when the live search fails; queries built in code from templates; failed pages replaced from a 12-URL pool; search snippets used as PARTIAL, never-counted evidence |
| Optional Tavily search (used only with your own free `TAVILY_API_KEY`) | **Working** (optional) | off without a key; per-query fallback to SearXNG on error or no credits, reason logged; for pages our own fetch cannot read (Reddit 403s, bot walls), the page text Tavily returns with demand results, then its Extract API, is used instead, labelled by origin (`tavily-search-raw`, `tavily-extract`) and still read by the isolated reader with quotes matched word for word |
| Isolated page reader (no tools, structured fields only) | **Working** | `app/services/reader.py`; quotes, names and prices not found on the page are dropped in code; bot-check pages are skipped |
| Claim extraction + code quote check + cross-family Claim Checker + Evidence Ledger | **Working** | unsupported claims rewritten as ASSUMPTION, never deleted |
| Idea variants, theory of value, competitor table, compliance quick check, Mom Test script | **Working** | |
| Desk-evidence gate computed by code; explanation (recommendation first); devil's advocate; 2-3 options; override needs a typed reason | **Working** | `app/gates.py`, `app/approval.py` |
| Lean Canvas with labeled assumptions; riskiest-assumption-first; Experiment Designer; founder approval locks the experiment | **Working** | |
| Local landing page with a real waitlist form (consent line, email + timestamp only, delete link), served only after Outbox approval | **Working** | demo-audience sign-ups tagged and never counted |
| Experiment gate states (NOT_STARTED, IN_PROGRESS, INSUFFICIENT_SAMPLE, VERDICT); no verdict before the window closes | **Working** | |
| Experiment replay fixtures (12/100 and 130/100 sign-ups) | **MOCKED** | same gate code; never evidence |
| Build loop: Builder, independent Test Writer, code test runner (exit code = gate), 3 tries then founder | **Working** | product = digital guide/template pack (HTML + Markdown) |
| Pricing, DRAFT terms/privacy/refund policies, compliance checklist with official sources, consistency check | **Working** | "not legal advice" on every policy |
| Store page and launch posts queued in the Outbox | **Working** | |
| Outbox tier-1 "publish page / post / send email" connectors | **MOCKED** | approved items are written locally, nothing leaves the machine |
| Checkout / order_received event | **MOCKED** | no payment code; no money exists or moves |
| Automatic delivery of the digital product | **MOCKED** | local download token, idempotent per order id |
| Refund requests | **MOCKED** | recorded, access revoked, reply drafted; only the founder refunds, in their own provider |
| Phase 6 metrics (visits, orders, tickets) | **MOCKED** | `evals/fixtures/metrics_mock.json` |
| Support tickets in Phase 6 | **MOCKED** | replies are drafts in shadow mode until the founder signs off, then go through the Outbox |
| Interview rehearsal personas | **MOCKED** | answers stored as ASSUMPTION |
| Persevere-or-pivot memo (recommendation computed by code, first sentence) | **Working** | |
| Scripted LLM used only by the test suite | **STUBBED** | `tests/conftest.py`; never used by the app |
| Kill switch, decision log, cost meter, citation dashboard, hypothesis tracker, founder-control panel | **Working** | |
| Method library (`knowledge/*.md`): short cards on where evidence lives, the Mom Test, niche-down, riskiest assumption, smoke tests, pricing, red flags | **Working** | added to the matching agent's instructions as guidance, never evidence; card ids logged in `decision_log.json` |

Every mock is registered in `config/mocks.yaml`, which also drives the MOCKED / STUBBED badges in the UI.

## Architecture

A plain-code orchestrator (`app/orchestrator/orchestrator.py`) owns the phases, gates and every side effect; LLM agents (`app/agents/`) only return typed Pydantic drafts, claims and options. Each gate rule is locked with a hash and timestamp before its evidence is gathered, and `app/gates.py` computes the verdict from the Evidence Ledger; the LLM only explains it, recommendation first, and the founder decides (overrides need a typed reason). The run plan and search keywords are fixed from the parsed brief before any web page is read (queries are built from them in code), page text goes to an isolated reader with no tools, and every value carries a provenance tag so web text can never choose a recipient or publish target. The Outbox is the only path outward: tier 0 automatic, tier 1 founder approval one by one (connectors mocked), tier 2 (money, credentials) always blocked. Details, diagrams and the sale-to-cash design: [ARCHITECTURE.md](ARCHITECTURE.md).

## Models and free resources

| Role | Model (Ollama tag) | Why |
|---|---|---|
| intake, planner, idea scout, claim extractor, gate explainer, copywriter, builder, analyst | `gpt-oss:120b` (Apache-2.0) | strongest open model we can name; pulled by `docker compose up` (needs a large GPU, e.g. 80 GB) |
| page reader, claim checker, policy guard, devil's advocate, test writer, coach, eval judge | `qwen3:32b` (Apache-2.0) | a **different model family** checks what gpt-oss writes; the page reader's output is also verified in code |
| shared memory / lessons relevance filter | `nomic-embed-text` (Apache-2.0) | local embeddings |
| optional `safeguard` profile | `gpt-oss-safeguard:20b` | Policy Guard alternative, loaded one after another |
| fallback for the checker roles | `qwen2.5:7b` (Apache-2.0), model key `qwen25-7b` | same family split; use when qwen3:8b is not pulled |

**Default models changed after the committed demo run.** `docker compose up` now pulls `gpt-oss:120b` + `qwen3:32b` + `nomic-embed-text` (~85 GB) and needs roughly an 80 GB GPU to keep both loaded; smaller GPUs swap models (much slower). Lighter setup for a 24 GB GPU (what our demo used): `PULL_MODELS="gpt-oss:20b qwen3:8b nomic-embed-text"` plus `ROLE_<ROLE>=gpt-oss-20b` for the writer roles and `ROLE_<ROLE>=qwen-8b` for the checker roles in `.env`. **The committed demo run (`outputs/`) used:** gpt-oss:20b for the writer roles, `qwen2.5:7b` for every checker role (`ROLE_<ROLE>=qwen25-7b` in `.env`), and no embedding model, so lessons relevance used the built-in keyword-overlap fallback. Ollama ran natively on the host and only SearXNG ran in Docker. The `decision_log.json` `model` field shows the exact tag of every call.

- Everything is free and local by default: Ollama serves the models, SearXNG is self-hosted search, storage is a SQLite file in `data/`. No API keys, no paid services and no accounts are required.
- Optional search provider: **Tavily** (hosted search API for agents). `SEARCH_PROVIDER=auto` (default) uses it only when you add your own key (`TAVILY_API_KEY` in `.env`; free tier about 1,000 credits a month, 1 credit per search; 6-8 searches per Phase 1 run in our tests). With no key, or when Tavily errors or runs out of credits, that query falls back to SearXNG and the decision log `note` says why. `SEARCH_PROVIDER=searxng` never calls Tavily. Demand searches are limited to the gate's community sites. Comparison on three briefs: `evals/results/search_tavily.json`.
- Search: self-hosted SearXNG (`searxng/settings.yml`) with engines routed per purpose in `config/search.yaml` (demand: hackernews, duckduckgo, bing, mojeek, Stack Exchange sites; competitors and pricing: duckduckgo, bing, startpage, mojeek, qwant, google cse). Responses are cached for 24 h per (query, engines) and live queries are sent one at a time, 1 s apart, to avoid rate-limit suspensions. Results are deduped, capped at 2 per domain, and template galleries in `config/search_filters.yaml` are moved to the end. From a single home IP some engines still refuse (CAPTCHA or suspension); every run logs which engines answered.
- Profiles: `PROFILE=demo-fast` (default: 5 results/query, 3 queries, 5 pages, checks only gate claims), `PROFILE=quality` (larger caps, claim checker escalates to gpt-oss:20b on failure), `PROFILE=safeguard`. Per-role override: `ROLE_<ROLE>=<model-key>` (e.g. `ROLE_CLAIM_CHECKER=gpt-oss-20b`; the app warns when a checker shares the writer's family).
- VRAM: estimated ~20 GB for gpt-oss:20b + qwen3:8b + embeddings with q8_0 KV cache. Measured peak VRAM during Phase 1 runs on an RTX 3090 (gpt-oss:20b + qwen2.5:7b): **19.6-20.1 GB** (whole-GPU `nvidia-smi`, including ~1.5 GB used by the desktop; recorded in `outputs/runs/<run>/timing.json`).
- Context length: the app calls Ollama's native `/api/chat` with `options.num_ctx` from `config/models.yaml` (gpt-oss:20b 16384, qwen 8192); `ollama ps` and the Ollama server log confirm these sizes. The optional `openai_compat` provider (OpenAI-compatible `/v1`) ignores per-request `num_ctx`; with it, set `OLLAMA_CONTEXT_LENGTH` on the Ollama server instead.
- Timing target: intake to desk-gate verdict in about 2 minutes in `demo-fast` on the RTX 3090. Measured with live search: **12-66 s** across five runs before the search upgrade; **60-78 s** after it (more queries, up to 12 candidate pages per purpose; `evals/results/search_before_after.md`).

## Cost per run

**About $0.00 per run** in API fees: all models run locally (electricity not included).

The cost meter (`app/services/cost.py`) records tokens in/out, latency and cache hits for every LLM call and writes `outputs/runs/<run>/cost.json`; the UI shows cost so far. It also reports a *reference* cost: what the same tokens would cost on a hosted open-weight endpoint.

`reference cost = Σ_calls (tokens_in × price_in + tokens_out × price_out) / 1,000,000`

Reference prices used (ASSUMPTION, typical public prices for hosted open models in late 2026, not quotes): gpt-oss-20b $0.05 in / $0.20 out per million tokens; qwen3-8b $0.035 / $0.138; edit them in `config/models.yaml`. Measured Phase 1 runs used **5k-21k tokens** (19-24 LLM calls), a reference cost under $0.01 per run; see `outputs/cost.json`.

## Demo video

Not recorded yet.

## What our system will NOT do

- Promise income or success. Financial projections only appear as labeled ASSUMPTION scenarios.
- Write fake reviews, testimonials, ratings, sign-ups, social-proof numbers, or countdown/scarcity urgency, in any language (deterministic rules + a policy model from a different family; see `config/policy_rules.yaml`, `config/policy.md`).
- Pose as the founder, a customer or another brand.
- Hold, move, charge or refund money; there is no payment code at all (a test greps for payment SDKs). Store passwords, card numbers or credentials. Create accounts.
- Publish, post, send or spend anything without the founder approving that item in the Outbox.
- Let text from a web page choose an action, recipient or publish target (isolated reader, provenance tags, Outbox rejects web-provenance targets; planted-injection test).
- Count simulated personas, replay fixtures or demo-audience sign-ups as evidence at a gate.
- Give a gate verdict before an experiment window closes, or change a verdict because the founder pushes back without new evidence.
- Build physical goods, financial/investment/crypto products, or health or legal advice products (blocked at intake).
- Paywall its own core features: the whole system is Apache-2.0.

## How the project stays alive after the hackathon

- **Maintainers:** the founding team maintains `main`; contributions via pull requests with the smoke tests passing.
- **Roadmap:** see [ARCHITECTURE.md#roadmap](ARCHITECTURE.md#roadmap): real connectors behind the same Outbox approval (founder's own store, newsletter), Arabic-first prompts and briefs, more product types with their own test runners, larger eval sets.
- **Community:** example briefs and labeled eval data in `evals/` are easy first contributions; every prompt is a plain file in `prompts/`.
- **Funding:** no paid tier of our own. Hosting stays with each founder (local or their own GPU); we will apply for open-source and university innovation grants and accept sponsorship that does not change the rules above.
