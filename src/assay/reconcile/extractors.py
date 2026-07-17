"""Answer extractors mirroring lm-eval's GSM8K filters.

Two extraction paths that lm-eval ships for the *same* GSM8K generations:

* strict-match   : requires the canonical "#### <number>" answer delimiter.
                   Regex mirrors lm-eval's ``#### (\\-?[0-9\\.\\,]+)``.
* flexible-extract: takes the LAST number-like token anywhere in the output.
                   Regex mirrors lm-eval's ``(-?[$0-9.,]{2,})|(-?[0-9]+)``.

These approximate the intent of lm-eval's filters (delimiter-anchored vs
last-number), which is what produces the score gap on identical text. The exact
per-version regexes are pinned in the production adapter.
"""
from __future__ import annotations

import re
from typing import Optional

_STRICT = re.compile(r"####\s*(-?[0-9][0-9,]*\.?[0-9]*)")
_FLEX = re.compile(r"(-?[$0-9][0-9,]*\.?[0-9]*)|(-?[0-9]+)")


def normalize_number(s: Optional[str]) -> Optional[str]:
    """Canonicalize a numeric string: strip $ and commas, drop a trailing dot,
    collapse 18.0 -> 18. Returns None if it is not a number."""
    if s is None:
        return None
    s = s.strip().lstrip("$").replace(",", "")
    s = s.rstrip(".")
    if s in ("", "-", "+"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if f == int(f):
        return str(int(f))
    return repr(f)


def strict_match(text: str) -> Optional[str]:
    """Return the number after the last '####' delimiter, or None if absent."""
    last = None
    for last in _STRICT.finditer(text):
        pass
    if last is None:
        return None
    return normalize_number(last.group(1))


def flexible_extract(text: str) -> Optional[str]:
    """Return the last number-like token anywhere in the text, or None."""
    last = None
    for m in _FLEX.finditer(text):
        last = m.group(0)
    return normalize_number(last)
