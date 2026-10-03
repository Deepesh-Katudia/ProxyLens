"""JSON helpers: strict structured-output schemas and lenient JSON parsing."""

import copy
import json
import re
from typing import Any

from pydantic import BaseModel

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_DROP_KEYS = ("title", "default", "description", "examples")


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A pydantic model's schema in the shape OpenAI-style strict mode accepts.

    Strict structured outputs require every property to be listed in `required`
    (optional ones are nullable instead), `additionalProperties: false` on every
    object, and no `$ref`/`default`/`title` keywords.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "properties":
                # Property names are data, not keywords: keep a field called "title".
                out[key] = {name: resolve(sub) for name, sub in value.items()}
            elif key not in _DROP_KEYS:
                out[key] = resolve(value)
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a model's JSON reply, tolerating code fences and surrounding prose."""
    candidate = text.strip()
    if fenced := _FENCE.match(candidate):
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object, got {type(value).__name__}")
    return value
