"""Provider `local_transformers`: small open-weight models run in the app process with Hugging Face
transformers (no Ollama). Weights are downloaded once into HF_HOME (a Docker volume), never per request.

  - MiniCheck-Flan-T5-Large (MIT): support probability of a claim given a document (claim_checker role)
  - bge-reranker-v2-m3 (Apache-2.0): cross-encoder relevance score (reranker role)

torch/transformers are imported lazily, so the rest of the app (and the tests) run without them.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Optional

from app.llm.client import ModelSpec

_LOCK = threading.Lock()
_LOADED: dict[str, tuple[Any, Any, str]] = {}


class LocalModelUnavailable(RuntimeError):
    pass


def _device(want: str) -> str:
    import torch
    if want in ("auto", "", None):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if want == "cuda" and not torch.cuda.is_available():
        return "cpu"
    return want


def _load(spec: ModelSpec, kind: str) -> tuple[Any, Any, str]:
    with _LOCK:
        if spec.key in _LOADED:
            return _LOADED[spec.key]
        try:
            import torch
            from transformers import (AutoModelForSeq2SeqLM, AutoModelForSequenceClassification,
                                      AutoTokenizer)
        except ImportError as e:  # pragma: no cover - depends on the install
            raise LocalModelUnavailable(f"{spec.name}: torch/transformers not installed ({e})") from e
        device = _device(str(spec.extra.get("device", "auto")))
        dtype = torch.float16 if device == "cuda" and spec.extra.get("fp16", True) else torch.float32
        tok = AutoTokenizer.from_pretrained(spec.name)
        cls = AutoModelForSeq2SeqLM if kind == "seq2seq" else AutoModelForSequenceClassification
        model = cls.from_pretrained(spec.name, torch_dtype=dtype).to(device).eval()
        _LOADED[spec.key] = (tok, model, device)
        return _LOADED[spec.key]


def unload(key: Optional[str] = None) -> None:
    with _LOCK:
        for k in [key] if key else list(_LOADED):
            _LOADED.pop(k, None)
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


# ----------------------------------------------------------------- MiniCheck --------------
def minicheck_scores(spec: ModelSpec, pairs: list[tuple[str, str]], batch: int = 8) -> list[float]:
    """P(supported) for each (document, claim) pair, as in the MiniCheck model card:
    input 'premise: <doc> hypothesis: <claim>', one decoder step, softmax over the '0'/'1' label tokens."""
    import torch
    tok, model, device = _load(spec, "seq2seq")
    neg = tok("0").input_ids[0]
    pos = tok("1").input_ids[0]
    out: list[float] = []
    for i in range(0, len(pairs), batch):
        chunk = pairs[i:i + batch]
        enc = tok([f"premise: {d} hypothesis: {c}" for d, c in chunk], max_length=int(spec.num_ctx or 2048),
                  truncation=True, padding=True, return_tensors="pt").to(device)
        dec = torch.zeros((len(chunk), 1), dtype=torch.long, device=device)
        with torch.no_grad():
            logits = model(**enc, decoder_input_ids=dec).logits[:, 0, :]
        probs = torch.softmax(logits[:, [neg, pos]].float(), dim=-1)[:, 1]
        out += [float(p) for p in probs.cpu()]
    return out


# ----------------------------------------------------------------- reranker ---------------
def rerank_scores(spec: ModelSpec, query: str, passages: list[str], batch: int = 16) -> list[float]:
    """Cross-encoder relevance in [0, 1] (sigmoid of the logit), one per passage."""
    import torch
    tok, model, device = _load(spec, "cls")
    out: list[float] = []
    for i in range(0, len(passages), batch):
        chunk = passages[i:i + batch]
        enc = tok([[query, p] for p in chunk], max_length=int(spec.num_ctx or 512), truncation=True,
                  padding=True, return_tensors="pt").to(device)
        with torch.no_grad():
            logits = model(**enc).logits.view(-1).float()
        out += [float(x) for x in torch.sigmoid(logits).cpu()]
    return out


# ----------------------------------------------------------------- text helpers -----------
def chunks(text: str, words: int = 300, overlap: int = 50) -> list[str]:
    ws = (text or "").split()
    if len(ws) <= words:
        return [" ".join(ws)] if ws else []
    step = max(1, words - overlap)
    return [" ".join(ws[i:i + words]) for i in range(0, max(1, len(ws) - overlap), step)]


def best_chunks(text: str, claim: str, k: int = 3, words: int = 300) -> list[str]:
    """Top-k chunks by content-word overlap with the claim (cheap lexical pre-selection)."""
    cs = chunks(text, words)
    if len(cs) <= k:
        return cs
    terms = {w for w in re.findall(r"\w{3,}", claim.lower())}
    scored = sorted(cs, key=lambda c: -len(terms & set(re.findall(r"\w{3,}", c.lower()))))
    return scored[:k]


def split_sentences(claim: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", (claim or "").strip()) if len(p.strip()) > 3]
    return parts or [claim]


def prefetch() -> list[str]:
    """Download (or confirm cached) the weights of every local_transformers model in models.yaml."""
    from huggingface_hub import HfApi, snapshot_download

    from app.config import load_yaml
    cfg = load_yaml("models.yaml")
    done = []
    for key, m in cfg["models"].items():
        if cfg["providers"][m["provider"]].get("kind") == "local_transformers":
            files = HfApi().list_repo_files(m["name"])
            weights = "*.safetensors" if any(f.endswith(".safetensors") for f in files) else "*.bin"
            snapshot_download(m["name"], allow_patterns=["*.json", "*.model", "*.txt", weights])
            done.append(m["name"])
    return done


if __name__ == "__main__":
    import sys
    if "--prefetch" in sys.argv:
        print("local_transformers weights ready:", prefetch())
