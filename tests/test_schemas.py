"""Every LLM-facing schema is sent with local $refs inlined (portable structured output)."""
import inspect
import json

from pydantic import BaseModel

from app import models
from app.llm.client import inline_refs


def test_all_schemas_inline_without_refs():
    n = 0
    for name, cls in inspect.getmembers(models, inspect.isclass):
        if issubclass(cls, BaseModel) and cls is not BaseModel:
            s = json.dumps(inline_refs(cls.model_json_schema()))
            assert "$ref" not in s, name
            n += 1
    assert n > 30
