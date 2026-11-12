"""Find secrets, personal data and prompt-injection phrasing in text.

Everything here is pattern matching. It catches well-known secret formats and
obvious injection phrasing; it is NOT a security boundary and will miss novel
or obfuscated attacks. Use it as a seatbelt, not a vault.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    kind: str  # e.g. "secret:aws_access_key", "pii:email", "injection"
    start: int
    end: int
    text: str

    @property
    def category(self) -> str:
        return self.kind.split(":", 1)[0]


# --- secrets ---------------------------------------------------------------
# High-precision formats only: each has a fixed prefix or structure.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key": re.compile(
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z]+ )?PRIVATE KEY-----"
    ),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}"),
    "openrouter_key": re.compile(r"\bsk-or-v1-[a-f0-9]{48,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack_token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "stripe_key": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "url_credentials": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]{3,}@[^\s]+", re.I),
    # key = value assignments with a long opaque value
    "assigned_secret": re.compile(
        r"(?i)\b[\w.-]*(?:secret|token|passw(?:or)?d|api[_-]?key|access[_-]?key)[\w.-]*"
        r"\s*[:=]\s*['\"]?(?P<value>[^\s'\"]{12,})"
    ),
}

# --- personal data ----------------------------------------------------------
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_SSN = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]?\d{2,4}){2,4}\b")


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card_ok(m: re.Match[str]) -> bool:
    digits = re.sub(r"\D", "", m.group())
    return 13 <= len(digits) <= 19 and len(set(digits)) > 1 and luhn_ok(digits)


def _ssn_ok(m: re.Match[str]) -> bool:
    area, group, serial = m.groups()
    return area not in {"000", "666"} and area[0] != "9" and group != "00" and serial != "0000"


def _ipv4_ok(m: re.Match[str]) -> bool:
    parts = [int(p) for p in m.group().split(".")]
    if any(p > 255 for p in parts):
        return False
    # Loopback, private and unspecified addresses are not personal data.
    a, b = parts[0], parts[1]
    return not (a in (0, 10, 127) or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31))


PII_PATTERNS: dict[str, tuple[re.Pattern[str], Callable[[re.Match[str]], bool] | None]] = {
    "email": (_EMAIL, None),
    "credit_card": (_CARD, _card_ok),
    "us_ssn": (_SSN, _ssn_ok),
    "ipv4": (_IPV4, _ipv4_ok),
    "phone": (_PHONE, None),
}

# --- prompt injection -------------------------------------------------------
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_INJECTION = [
    re.compile(
        r"\b(?:ignore|disregard|forget|override|skip)\s+(?:all\s+|any\s+|the\s+|your\s+|of\s+)*"
        r"(?:previous|prior|earlier|above|preceding|original|system)\s+"
        r"(?:instructions?|prompts?|rules?|directions?|guidelines?|messages?)"
    ),
    re.compile(
        r"\b(?:reveal|print|show|output|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+prompt|hidden\s+instructions?)"
    ),
    re.compile(r"\byou\s+are\s+(?:now\s+)?(?:in\s+)?(?:developer|debug|admin|god|jailbreak|dan)\s+mode\b"),
    re.compile(r"\byou\s+are\s+now\s+(?:dan|an?\s+unrestricted|unfiltered)\b"),
    re.compile(r"\bnew\s+(?:system\s+)?instructions?\s*:"),
    re.compile(r"(?:^|\n)\s*(?:system|assistant)\s*:\s*(?:you|ignore|from now on)"),
    re.compile(r"<\|?\s*(?:im_start|system|endoftext)\s*\|?>"),
    re.compile(r"\b(?:do\s+not|don't)\s+(?:tell|inform|alert)\s+the\s+user\b"),
]


def _normalize(text: str) -> str:
    """Casefold, NFKC, strip zero-width chars, collapse whitespace.

    Lengths can change, so injection findings report positions in the
    normalized text; they are used for flagging, never for redaction.
    """
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).casefold()
    return re.sub(r"[ \t]+", " ", text)


def find_secrets(text: str) -> list[Finding]:
    out: list[Finding] = []
    for name, pat in SECRET_PATTERNS.items():
        for m in pat.finditer(text):
            if name == "assigned_secret":
                value = m.group("value")
                # Skip placeholders and variable references, keep real-looking values.
                # Code (calls, indexing) is not a secret: real keys have no brackets.
                if (
                    any(c in value for c in "()[]")
                    or value.startswith(("$", "{", "<"))
                    or not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value))
                ):
                    continue
                out.append(Finding(f"secret:{name}", m.start("value"), m.end("value"), value))
            else:
                out.append(Finding(f"secret:{name}", m.start(), m.end(), m.group()))
    return _dedupe(out)


def find_pii(text: str) -> list[Finding]:
    out: list[Finding] = []
    for name, (pat, ok) in PII_PATTERNS.items():
        for m in pat.finditer(text):
            if ok is None or ok(m):
                out.append(Finding(f"pii:{name}", m.start(), m.end(), m.group()))
    return _dedupe(out)


def find_injection(text: str) -> list[Finding]:
    norm = _normalize(text)
    return [
        Finding("injection", m.start(), m.end(), m.group().strip())
        for pat in _INJECTION
        for m in pat.finditer(norm)
    ]


def scan(text: str) -> list[Finding]:
    return find_secrets(text) + find_pii(text) + find_injection(text)


def redact(text: str, findings: Iterable[Finding] | None = None) -> str:
    """Replace secret and PII spans with [REDACTED:<kind>] markers."""
    if findings is None:
        findings = find_secrets(text) + find_pii(text)
    spans = _dedupe([f for f in findings if f.category in ("secret", "pii")])
    for f in sorted(spans, key=lambda f: f.start, reverse=True):
        text = text[: f.start] + f"[REDACTED:{f.kind.split(':', 1)[1]}]" + text[f.end :]
    return text


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop findings overlapping an earlier, longer one."""
    kept: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.start, -(f.end - f.start))):
        if kept and f.start < kept[-1].end:
            continue
        kept.append(f)
    return kept
