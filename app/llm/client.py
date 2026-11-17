"""The model layer.  llm.call(role, messages, schema) -> validated Pydantic object.

Agents never name a model; they name a role. The role resolves to a model via config/models.yaml,
PROFILE overrides and ROLE_<NAME> env overrides.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import data_dir, env, load_yaml, profile
from app.services import events
from app.services.cost import record_call

T = TypeVar("T", bound=BaseModel)
CHECKING_ROLES = ("claim_checker", "policy_guard", "judge")


class LLMError(RuntimeError):
    """Typed error the orchestrator handles (after retries and escalation failed)."""

    def __init__(self, role: str, model: str, detail: str):
        super().__init__(f"{role} on {model}: {detail}")
        self.role, self.model, self.detail = role, model, detail


@dataclass
class ModelSpec:
    key: str
    name: str
    family: str
    provider_kind: str
    base_url: str
    num_ctx: int = 8192
    vram_gb_est: float = 0
    think: Any = None
    ref_in: float = 0.0
    ref_out: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)  # provider-specific settings (e.g. device, keep_alive)


@dataclass
class RoleSpec:
    role: str
    model: ModelSpec
    temperature: float = 0.2
    escalate_to: Optional[ModelSpec] = None
    checks: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def _model(key: str) -> ModelSpec:
    cfg = load_yaml("models.yaml")
    m = cfg["models"][key]
    prov = cfg["providers"][m["provider"]]
    base = prov.get("base_url", "")
    if prov.get("kind", "ollama") == "ollama" and env("OLLAMA_URL"):
        base = env("OLLAMA_URL")
    price = m.get("ref_usd_per_mtok") or {}
    return ModelSpec(key=key, name=m["name"], family=m.get("family", key), provider_kind=prov.get("kind", "ollama"),
                     base_url=base.rstrip("/"), num_ctx=int(m.get("num_ctx", 8192)), vram_gb_est=float(m.get("vram_gb_est", 0)),
                     think=m.get("think"), ref_in=float(price.get("in", 0)), ref_out=float(price.get("out", 0)),
                     extra={k: v for k, v in m.items() if k in MODEL_EXTRA_KEYS})


MODEL_EXTRA_KEYS = ("device", "dtype", "keep_alive", "license")


def resolve(role: str) -> RoleSpec:
    cfg = load_yaml("models.yaml")
    base = dict(cfg["roles"][role])
    base.update((profile().get("role_overrides") or {}).get(role, {}))
    override = os.environ.get(f"ROLE_{role.upper()}")
    if override:
        base["model"] = override
    esc = base.get("escalate_to")
    return RoleSpec(role=role, model=_model(base["model"]), temperature=float(base.get("temperature", 0.2)),
                    escalate_to=_model(esc) if esc else None, checks=base.get("checks"),
                    extra={k: v for k, v in base.items() if k not in {"model", "temperature", "escalate_to", "checks"}})


def config_warnings() -> list[str]:
    """Startup checks: VRAM budget and checker/writer family separation."""
    cfg = load_yaml("models.yaml")
    warnings: list[str] = []
    used = {resolve(r).model.key for r in cfg["roles"] if r != "judge"}
    total = sum(_model(k).vram_gb_est for k in used)
    # KV cache / context headroom per loaded LLM (estimate); local_transformers models have no KV cache
    headroom = 2.0 * sum(1 for k in used if _model(k).provider_kind != "local_transformers")
    if total + headroom > 24:
        warnings.append(f"Co-loaded models need ~{total + headroom:.0f} GB (models {total:.0f} + context {headroom:.0f}) > 24 GB.")
    for r in CHECKING_ROLES:
        spec = resolve(r)
        if spec.checks and spec.checks in cfg["roles"]:
            checked = resolve(spec.checks)
            if checked.model.family == spec.model.family:
                warnings.append(f"Checking role {r} uses the same model family ({spec.model.family}) as {spec.checks}.")
    return warnings


# ----------------------------------------------------------------- backends --------------
Backend = Callable[[ModelSpec, list[dict[str, str]], dict[str, Any], float], tuple[str, int, int]]
_BACKEND_OVERRIDE: Optional[Backend] = None  # tests install a STUBBED backend here


def set_backend(fn: Optional[Backend]) -> None:
    global _BACKEND_OVERRIDE
    _BACKEND_OVERRIDE = fn


def _http_backend(model: ModelSpec, messages: list[dict[str, str]], schema: dict[str, Any], temperature: float) -> tuple[str, int, int]:
    timeout = float(env("LLM_TIMEOUT", "240"))
    if model.provider_kind == "ollama":
        payload: dict[str, Any] = {
            "model": model.name, "messages": messages, "stream": False, "format": schema,
            "options": {"temperature": temperature, "num_ctx": model.num_ctx},
        }
        if model.think is not None:
            payload["think"] = model.think
        if model.extra.get("keep_alive") is not None:  # unload models the next steps do not need
            payload["keep_alive"] = model.extra["keep_alive"]
        r = httpx.post(f"{model.base_url}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        return body["message"]["content"], int(body.get("prompt_eval_count", 0)), int(body.get("eval_count", 0))
    payload = {"model": model.name, "messages": messages, "temperature": temperature,
               "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}}
    r = httpx.post(f"{model.base_url}/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    usage = body.get("usage", {})
    return body["choices"][0]["message"]["content"], int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


# ----------------------------------------------------------------- cache ------------------
_CACHE_LOCK = threading.Lock()


def _cache_key(spec: RoleSpec, model: ModelSpec, messages: list[dict[str, str]], schema_name: str) -> str:
    blob = json.dumps({"model": model.name, "t": spec.temperature, "ctx": model.num_ctx, "schema": schema_name,
                       "messages": messages}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    p = data_dir() / "llm_cache" / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _cache_put(key: str, value: dict[str, Any]) -> None:
    d = data_dir() / "llm_cache"
    d.mkdir(parents=True, exist_ok=True)
    with _CACHE_LOCK:
        (d / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local $ref/$defs so any JSON-schema-to-grammar backend can use the schema."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = dict(defs[node["$ref"].split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rstrip("`").strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


# ----------------------------------------------------------------- call -------------------
def call(role: str, messages: list[dict[str, str]], schema: type[T], *, run_id: Optional[str] = None,
         use_cache: bool = True, max_retries: int = 2, check: Optional[Callable[[T], Optional[str]]] = None,
         check_retries: int = 1) -> T:
    """Resolve the role's model, request JSON matching `schema`, validate, retry, escalate, log.

    `check` returns an error message for a schema-valid reply that is still wrong (e.g. a quote that is not
    on the page). The model gets `check_retries` retries with that message, then the call escalates. If every model fails
    the check, the last reply is returned and the caller's own code filter decides what to keep."""
    events.check_kill()
    spec = resolve(role)
    json_schema = inline_refs(schema.model_json_schema())
    sys_note = {"role": "system", "content": "Reply with one JSON object that matches this JSON schema. No prose.\n"
                + json.dumps(json_schema)}
    candidates = [spec.model] + ([spec.escalate_to] if spec.escalate_to else [])
    last_err = ""
    checked_out: Optional[T] = None
    for model in candidates:
        msgs = [sys_note] + list(messages)
        key = _cache_key(spec, model, msgs, schema.__name__)
        if use_cache:
            hit = _cache_get(key)
            if hit is not None:
                try:
                    obj = schema.model_validate_json(hit["content"])
                    if check is None or check(obj) is None:
                        record_call(run_id, role, model, 0, 0, 0.0, cache_hit=True)
                        return obj
                except ValidationError:
                    pass
        for attempt in range(max(max_retries, check_retries) + 1):
            events.check_kill()
            t0 = time.time()
            backend = _BACKEND_OVERRIDE or _http_backend
            try:
                content, tin, tout = backend(model, msgs, json_schema, spec.temperature)
            except (httpx.HTTPError, KeyError) as e:
                last_err = f"transport error: {e}"
                record_call(run_id, role, model, 0, 0, time.time() - t0, error=last_err)
                continue
            latency = time.time() - t0
            record_call(run_id, role, model, tin, tout, latency)
            try:
                obj = schema.model_validate_json(_extract_json(content))
            except ValidationError as e:
                obj = None
                last_err = str(e)[:1500]
                msgs = msgs + [{"role": "assistant", "content": content[:4000]},
                               {"role": "user", "content": "That JSON failed validation:\n" + last_err +
                                "\nReturn corrected JSON only."}]
                continue
            problem = check(obj) if check else None
            if problem is None:
                _cache_put(key, {"content": obj.model_dump_json(), "model": model.name})
                return obj
            checked_out, last_err = obj, problem
            if attempt >= check_retries:  # corrective retries per model, then escalate
                break
            msgs = msgs + [{"role": "assistant", "content": content[:4000]},
                           {"role": "user", "content": problem + "\nReturn corrected JSON only."}]
        if run_id:
            events.emit(run_id, "warn", f"{role}: {model.name} failed after retries; "
                        + ("escalating" if model is not candidates[-1] else "giving up"))
    if checked_out is not None:
        return checked_out
    raise LLMError(role, candidates[-1].name, last_err or "unknown failure")


def chat_text(role: str, messages: list[dict[str, str]], *, run_id: Optional[str] = None,
              num_predict: int = 64) -> str:
    """Plain-text chat (no JSON schema) for classifier models whose output is a fixed word (e.g. yes/no).
    Ollama provider only; the stubbed test backend is used when installed."""
    events.check_kill()
    spec = resolve(role)
    model = spec.model
    t0 = time.time()
    if _BACKEND_OVERRIDE:
        content, tin, tout = _BACKEND_OVERRIDE(model, messages, {"title": "text"}, spec.temperature)
    else:
        payload: dict[str, Any] = {"model": model.name, "messages": messages, "stream": False,
                                   "options": {"temperature": spec.temperature, "num_ctx": model.num_ctx,
                                               "num_predict": num_predict}}
        if model.think is not None:
            payload["think"] = model.think
        if model.extra.get("keep_alive") is not None:
            payload["keep_alive"] = model.extra["keep_alive"]
        try:
            r = httpx.post(f"{model.base_url}/api/chat", json=payload, timeout=float(env("LLM_TIMEOUT", "240")))
            r.raise_for_status()
        except httpx.HTTPError as e:
            record_call(run_id, role, model, 0, 0, time.time() - t0, error=str(e))
            raise LLMError(role, model.name, f"transport error: {e}") from e
        body = r.json()
        content, tin, tout = body["message"]["content"], int(body.get("prompt_eval_count", 0)), int(body.get("eval_count", 0))
    record_call(run_id, role, model, tin, tout, time.time() - t0)
    return content


def family_of(role: str) -> str:
    return resolve(role).model.family


def model_name(role: str) -> str:
    return resolve(role).model.name
