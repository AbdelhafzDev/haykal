"""Safe value addressing and interpolation for declarative skills."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy

_REFERENCE = re.compile(r"^\$\{([^}]+)}$")


class ValueNotFound(LookupError):
    """A declared workflow value does not exist."""


def get_path(root: object, path: str) -> object:
    current = root
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        raise ValueNotFound(path)
    return current


def resolve_value(value: object, context: Mapping[str, object]) -> object:
    if isinstance(value, str):
        match = _REFERENCE.fullmatch(value)
        if match:
            return deepcopy(get_path(context, match.group(1)))
        return value
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    return value


def public_input_echo(inputs: Mapping[str, object]) -> dict[str, object]:
    """Keep references opaque and exclude values explicitly marked secret."""

    echo: dict[str, object] = {}
    for name, value in inputs.items():
        if isinstance(value, Mapping) and ("secret" in value or value.get("type") == "secret"):
            echo[name] = {"redacted": True}
        else:
            echo[name] = deepcopy(value)
    return echo
