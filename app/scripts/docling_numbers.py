"""Conservative lexical evidence, not medical interpretation or locale guessing."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

POLICY = "docling-numeric-evidence-v2"
# Consume comma/dot/grouping sequences atomically, including unsupported forms.
# A numeric fragment inside 0,09, 1.2.3 or 1 234 must never become a plain scalar.
ATOM = re.compile(
    r"(?:(?:[<>]=?|[\u2264\u2265])\s*|(?<![\w.,'\u2019]))[+\-\u2212]?"
    r"(?:\d+(?:(?:[.,]\s*|['\u2019\u00a0\u202f]| (?=\d{3}(?:\D|$)))\d+)*|\.\d+)"
    r"(?:[eE][+\-\u2212]?\d+)?%?(?!\w|[.,]\s*\d)")
SCALAR = re.compile(r"[+\-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def lexemes(text):
    matches = list(ATOM.finditer(text))
    result = []
    for index, match in enumerate(matches):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        raw = text[start:end]
        canonical = raw.replace("\u2212", "-")
        reasons = []
        if "," in raw:
            reasons.append("COMMA_DECIMAL_OR_GROUPING")
        if re.search(r"['\u2019\u00a0\u202f]|\d \d", raw):
            reasons.append("GROUPING_OR_COMPOSITE_UNRESOLVED")
        if re.match(r"[<>\u2264\u2265]", raw):
            reasons.append("BOUND_NOT_POINT_VALUE")
        if re.match(r"[+\-]?0\d", canonical):
            reasons.append("LEADING_ZERO_NONDECIMAL")
        if "\ufffd" in text[max(0, start-1):min(len(text), end+1)] or text[max(0,start-1):start] == "?":
            reasons.append("DAMAGED_SYMBOL_ADJACENT")
        if text[max(0,start-1):start] in ("\u2013", "\u2014", "~", "\u2248"):
            reasons.append("UNKNOWN_SIGN_OR_APPROXIMATION")
        if text[max(0,start-1):start] in (",", ".", "'", "\u2019") or text[end:end+1] in (",", ".", "'", "\u2019"):
            reasons.append("NUMERIC_PUNCTUATION_ADJACENT_UNRESOLVED")
        if text[max(0,start-1):start] in ("/", ":") or text[end:end+1] in ("/", ":"):
            reasons.append("COMPOSITE_OR_RATIO")
        # Relations between adjacent numbers are evidence, not unary signs or SD/CI assignments.
        for other, left in ((index-1, True), (index+1, False)):
            if not 0 <= other < len(matches):
                continue
            neighbor = matches[other]
            original_gap = text[neighbor.end():start] if left else text[end:neighbor.start()]
            gap = original_gap.strip()
            if original_gap and not gap:
                reasons.append("ADJACENT_NUMERIC_UNRESOLVED")
            if not gap and (raw.startswith("+") if left else neighbor.group().lstrip().startswith("+")):
                reasons.append("COMPOSITE_OR_RATIO")
            if re.fullmatch(r"(?:[-\u2013\u2014\u2212]|to)", gap, flags=re.I) or (
                    left and not gap and raw.startswith(("-", "\u2212"))):
                reasons.append("RANGE_COMPONENT")
            if not gap and not left and neighbor.group().lstrip().startswith(("-", "\u2212")):
                reasons.append("RANGE_COMPONENT")
            if gap in ("/", ":", "\\", "\u00d7", "*", "x", "+"):
                reasons.append("COMPOSITE_OR_RATIO")
            if gap in ("\u00b1", "+/-", "+ / -"):
                reasons.append("PAIRED_STATISTIC_UNRESOLVED")
        if re.search(r"\d\s*\(", text) and len(matches) > 1:
            reasons.append("COMBINED_STATISTIC_UNRESOLVED")
        if text.strip() == "(" + raw + ")":
            reasons.append("PARENTHESIZED_VALUE_UNRESOLVED")
        unit = "%" if raw.endswith("%") else ""
        scalar = canonical.removesuffix("%")
        if not SCALAR.fullmatch(scalar) and not reasons:
            reasons.append("UNKNOWN_NUMERIC_FORM")
        parsed = ""
        if not reasons and SCALAR.fullmatch(scalar):
            try:
                number = Decimal(scalar)
                if number.is_finite():
                    parsed = str(number)
            except InvalidOperation:
                pass
        if not parsed and not reasons:
            reasons.append("UNKNOWN_NUMERIC_FORM")
        fields = dict(numeric_policy=POLICY, source_char_start=str(start), source_char_end=str(end),
            raw_token=raw, parsed_number=parsed, unit_suffix=unit,
            numeric_ambiguity=";".join(sorted(set(reasons))),
            normalization_rule="unicode-minus-and-decimal-dot" if parsed else "unresolved-no-normalization",
            context_sha256=hashlib.sha256(text.encode()).hexdigest())
        fields["numeric_evidence_sha256"] = digest(fields)
        result.append(fields)
    return result


FIELDS = ["numeric_policy", "source_char_start", "source_char_end", "normalization_rule",
          "context_sha256", "numeric_evidence_sha256"]


def validate(candidate):
    """Re-lex the full original context; stored flags/parsed numbers are never trusted."""
    if candidate.get("numeric_policy") != POLICY:
        raise ValueError("legacy Docling numeric evidence; rescan local PDFs with the current adapter")
    for value in lexemes(candidate.get("context", "")):
        if (value["source_char_start"], value["source_char_end"]) == (
                candidate.get("source_char_start"), candidate.get("source_char_end")):
            if all(candidate.get(key) == expected for key, expected in value.items()):
                return value
            break
    raise ValueError("Docling numeric evidence does not match a complete source lexeme and normalization rule")
