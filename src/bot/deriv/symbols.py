from __future__ import annotations

import re

_RE_VOL = re.compile(r"^R_(\d+)$")
_RE_VOL_1S = re.compile(r"^1HZ(\d+)V$")
_RE_JUMP = re.compile(r"^JD(\d+)$")
_RE_BOOM = re.compile(r"^BOOM(\d+)(N)?$")
_RE_CRASH = re.compile(r"^CRASH(\d+)(N)?$")
_RE_STEP = re.compile(r"^STEPINDEX(\d+)$")

_SPECIAL_NAMES: dict[str, str] = {
    "RDBULL": "Bull Market Index",
    "RDBEAR": "Bear Market Index",
}


def display_name_for_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()

    if s in _SPECIAL_NAMES:
        return _SPECIAL_NAMES[s]

    m = _RE_VOL.fullmatch(s)
    if m:
        return f"Volatility {m.group(1)} Index"

    m = _RE_VOL_1S.fullmatch(s)
    if m:
        return f"Volatility {m.group(1)} (1s) Index"

    m = _RE_JUMP.fullmatch(s)
    if m:
        return f"Jump {m.group(1)} Index"

    m = _RE_BOOM.fullmatch(s)
    if m:
        return f"Boom {m.group(1)} Index"

    m = _RE_CRASH.fullmatch(s)
    if m:
        return f"Crash {m.group(1)} Index"

    m = _RE_STEP.fullmatch(s)
    if m:
        raw = m.group(1)
        if len(raw) == 1:
            return f"Step Index {raw}"
        return f"Step Index {raw[0]}.{raw[1:]}"

    return s


def is_synthetic_symbol(symbol: str) -> bool:
    s = str(symbol or "").strip().upper()
    return (
        bool(_RE_VOL.fullmatch(s))
        or bool(_RE_VOL_1S.fullmatch(s))
        or bool(_RE_JUMP.fullmatch(s))
        or bool(_RE_BOOM.fullmatch(s))
        or bool(_RE_CRASH.fullmatch(s))
        or bool(_RE_STEP.fullmatch(s))
        or s in _SPECIAL_NAMES
    )