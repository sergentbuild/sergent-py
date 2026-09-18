"""Mint and admit framework-owned bookkeeping identifiers. @sergent/docs/execution-model.md"""

from __future__ import annotations

import re
import uuid

_ID_RE = re.compile(r"^([a-z][a-z0-9]*)_[0-9a-f]{32}$")
_PREFIX_RE = re.compile(r"^[a-z][a-z0-9]*$")


def new_id(prefix: str) -> str:
    """Mint a framework identifier with a validated prefix. @sergent/docs/execution-model.md"""
    if _PREFIX_RE.fullmatch(prefix) is None:
        msg = f"invalid id prefix: {prefix!r}"
        raise ValueError(msg)
    return f"{prefix}_{uuid.uuid4().hex}"


def checked_id(value: str, *prefixes: str) -> str:
    """Admit a framework identifier, optionally from bounded prefixes. @sergent/docs/execution-model.md"""
    match = _ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        msg = "id must match '<prefix>_<32 lowercase hex chars>'"
        raise ValueError(msg)
    if not prefixes:
        return value
    if match.group(1) not in set(prefixes):
        expected = ", ".join(sorted(prefixes))
        msg = f"id prefix must be one of: {expected}"
        raise ValueError(msg)
    return value
