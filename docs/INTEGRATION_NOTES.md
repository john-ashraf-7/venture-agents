# Integration notes: reranker → search

Status: `app/services/rerank.py` is built and tested, but **not wired into search yet** (the search
package is being changed in parallel). This note says how to wire it.

## Where it goes

Between the SearXNG results and fetching, per purpose:

```python
from app.services import rerank

purpose = rerank.purpose_text("demand", problem=terms.problem)           # or:
# rerank.purpose_text("competitors", product_type=terms.product_type, audience=terms.audience)
# rerank.purpose_text("pricing", competitor=name)
ranked = rerank.rerank(purpose, results, top_k=caps["max_pages"])        # results: list of dicts
urls_to_fetch = [r["url"] for r in ranked]
```

- Input: SearXNG result dicts with `url`, `title`, `snippet` (or `content`), `engines`. Extra keys are kept.
- Output: new dicts, best first, each with `rerank_score` in [0, 1] (sigmoid of the cross-encoder logit).
- Optional `min_score=` drops weak matches; leave it off until scores are checked on real runs.
- Purpose templates live in `config/rerank_purposes.yaml`.

## Model and cost

- Role `reranker` in `config/models.yaml` → `bge-reranker-v2-m3` (`BAAI/bge-reranker-v2-m3`, Apache-2.0),
  provider `local_transformers`, `device: cpu` by default. `RERANKER_DEVICE=cuda` (or `device: auto`)
  uses the GPU (~1.2 GB in fp16).
- Weights download once into `HF_HOME` (the `hf_cache` Docker volume), on the first call, never per request.
- Tests install a STUBBED scorer with `rerank.set_scorer(fn)`.
