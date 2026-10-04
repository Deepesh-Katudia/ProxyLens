"""Issuer name from a notice's text (moved from scripts/harvest_notices.py)."""

import re

_COMPANY = re.compile(
    r"(?i:members|shareholders)\s+(?i:of)\s+(?:M/s\.?\s*)?(?:(?i:the)\s+)?"
    r"([A-Z][A-Za-z0-9&.,()'\- ]{2,90}?\b(?:LIMITED|Limited|LTD|Ltd)\b\.?)"
)
_NOTICE_START = re.compile(r"hereby\s+given", re.IGNORECASE)
OPENING_CHARS = 600  # the notice's first sentence names the issuer
_ANY_COMPANY = re.compile(
    r"\b([A-Z][A-Za-z0-9&.'\- ]{1,60}?\s(?:LIMITED|Limited|LTD\.?|Ltd\.?))(?![A-Za-z])"
)
# Names that appear in nearly every notice but are not the issuer.
_NOT_ISSUER = re.compile(
    r"stock exchange|bse|depositor|central depository|kfin|intime|link|registrar|"
    r"bigshare|cameo|skyline|purva|beetal|niche|maheshwari|adroit|alankit|"
    r"satellite|abhipra|in favour|private limited|pvt",
    re.IGNORECASE,
)
FIRST_PAGES_FOR_NAME = 3


_LEADING_FILLER = frozenset(
    {"for", "resolved", "that", "agm", "egm", "notice", "of", "the", "members",
     "shareholders", "m/s", "m/s.", "to", "and", "by", "order", "board"}
)  # fmt: skip


_NAME_CONNECTORS = frozenset({"of", "and", "&", "the"})


def _clean_name(name: str) -> str:
    """Keep the capitalised run before "Limited": drop prose ("Thanking you Yours
    faithfully For"), filler ("RESOLVED THAT") and numbering ("AGM Notice 2024-25 01")."""
    tokens = name.strip(" ,.").split()
    lowercase = [
        i for i, t in enumerate(tokens[:-1]) if t[:1].islower() and t not in _NAME_CONNECTORS
    ]
    if lowercase:
        tokens = tokens[lowercase[-1] + 1 :]
    while len(tokens) > 2 and (
        tokens[0].lower() in _LEADING_FILLER or any(c.isdigit() for c in tokens[0])
    ):
        tokens = tokens[1:]
    return " ".join(tokens)


def guess_company(pages: list[str]) -> str:
    """Issuer name: the 'Members of XYZ Limited' phrase, else the most frequent
    '... Limited' on the first pages that isn't an exchange, depository or registrar."""
    text = " ".join(" ".join(pages).split())
    start = _NOTICE_START.search(text)
    opening = text[start.start() : start.start() + OPENING_CHARS] if start else ""
    for scope in (opening, text):
        match = _COMPANY.search(scope)
        if match and not _NOT_ISSUER.search(_clean_name(match.group(1))):
            return _clean_name(match.group(1))
    head = " ".join(" ".join(pages[:FIRST_PAGES_FOR_NAME]).split())
    names = [_clean_name(m) for m in _ANY_COMPANY.findall(head)]
    names = [n for n in names if not _NOT_ISSUER.search(n) and len(n.split()) >= 2]
    if not names:
        return ""
    counts: dict[str, int] = {}
    for name in names:
        key = name.upper().rstrip(".")
        counts[key] = counts.get(key, 0) + 1
    best = max(counts, key=lambda k: counts[k])
    return next(n for n in names if n.upper().rstrip(".") == best)
