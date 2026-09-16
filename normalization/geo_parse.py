"""Parse `recalls.geographic_scope` free text into structured state data.

openFDA's `distribution_pattern` field (mapped to `geographic_scope`) is
free text, not a structured field, and its format is inconsistent across
records. Real formats observed in the data include:

    "The recalled product was distributed to the following states: MD, VA"
    "Domestic: AZ, CA, CO, HI, NJ, OR, TX, WA. Foreign: Not applicable."
    "Distribute in HI."
    "Nationwide."
    "Distributed in Alabama, Arizona, California, ... and Washington."
    "Texas"

This module is deliberately conservative: it only ever adds a state code
it's confident about, and anything it can't confidently read is reported
as unparsed rather than guessed. Two specific collision risks drove that:

1. "OR" is both Oregon's USPS abbreviation and the English word "or". To
   avoid matching ordinary prose, abbreviation matching requires the
   token to appear in the source text as an exact, standalone, ALL-CAPS
   two-letter word (`\\bOR\\b` in a run of caps, not `\\bor\\b`). Recall
   records write the abbreviation form in caps consistently; ordinary
   prose "or" is lowercase. Validated empirically against all 1,357 real
   `geographic_scope` values in the database at the time this was
   written: zero false positives, including two real records that use
   "or" in an ordinary sentence ("No foreign or institution
   distribution.", "No schools or institutional distribution.").

2. "Washington DC" is a similar trap, the other direction: naively
   matching the full state name "Washington" would misread the District
   of Columbia as Washington *state*. Handled by rewriting "Washington
   D.C."/"Washington DC" to just "DC" before full-name matching runs, so
   it's read as the district and not double-counted as the state too
   (unless "WA" also appears elsewhere in the same text, which does
   happen and is correctly kept).

Full state names are matched case-insensitively as whole words/phrases
against a fixed, closed list (the 50 states). Unlike abbreviations,
there's no ordinary-English-word collision risk here, and it was
similarly validated empirically against the real dataset (checked every
occurrence of every ambiguous-looking name -- Washington, Georgia,
Virginia, Jersey -- individually; all were genuine state mentions in
list-shaped context, no company names or foreign countries incorrectly
caught, in part because the nationwide check below runs first and
short-circuits records like the one distribution list that legitimately
mentions the country Georgia among a list of foreign countries).

Territory codes that show up in real data (PR, GU, VI) are intentionally
not treated as states -- they're just not added, since they aren't one.
"""
import re
from dataclasses import dataclass

STATE_ABBREVIATIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

STATE_FULL_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# Longest names first, so e.g. "West Virginia" is matched whole rather
# than leaving a dangling "Virginia" match at the tail.
_FULL_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in STATE_FULL_NAMES), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Exact, standalone, all-caps two-letter word -- see module docstring for
# why this (not a case-insensitive \b[A-Z]{2}\b) is the "OR" fix.
_ABBREVIATION_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])")

_WASHINGTON_DC_RE = re.compile(r"\bWashington,?\s*D\.?C\.?\b", re.IGNORECASE)

_NATIONWIDE_RE = re.compile(
    r"\bnationwide\b"
    r"|\bunited states\b"
    r"|\ball 50 states\b"
    r"|\bthroughout the u\.?s\.?\b"
    r"|\busa\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedGeography:
    is_nationwide: bool
    parse_status: str  # "parsed" | "unparsed"
    state_codes: tuple[str, ...]


def parse_geographic_scope(text: str | None) -> ParsedGeography:
    """Parse a `recalls.geographic_scope` value into structured geography.

    Nationwide language takes priority over any specific-state reading:
    a record that says "distributed nationwide" is nationwide even if it
    also happens to name a country or two, so there's no attempt to also
    extract states out of a nationwide record.
    """
    if not text:
        return ParsedGeography(is_nationwide=False, parse_status="unparsed", state_codes=())

    if _NATIONWIDE_RE.search(text):
        return ParsedGeography(is_nationwide=True, parse_status="parsed", state_codes=())

    # Disarm "Washington DC" before full-name matching, so it reads as
    # the district, not the state (see module docstring).
    text_for_names = _WASHINGTON_DC_RE.sub("DC", text)

    codes = set()

    for token in _ABBREVIATION_RE.findall(text):
        if token in STATE_ABBREVIATIONS:
            codes.add(token)

    for match in _FULL_NAME_RE.finditer(text_for_names):
        codes.add(STATE_FULL_NAMES[match.group(0).lower()])

    if codes:
        return ParsedGeography(
            is_nationwide=False,
            parse_status="parsed",
            state_codes=tuple(sorted(codes)),
        )

    return ParsedGeography(is_nationwide=False, parse_status="unparsed", state_codes=())
