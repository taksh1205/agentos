"""Deterministic numeric checks complement, rather than replace, semantic review."""

import calendar
import json
import math
import re

NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?(?:\s*%)?")


def numbers(text):
    # Ignore ISO periods; their component integers are not analytic assertions.
    text = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", "", text)
    text = re.sub(r"(?<=\d)\s+per\s*cent\b", "%", text, flags=re.I)
    values = []
    for match in NUMBER.finditer(text):
        value = match.group().strip()
        percent = value.endswith("%")
        number = float(value.rstrip("%").replace(",", "").strip())
        values.append(number / 100 if percent else number)
    return values


def unsupported_numbers(summary, computed):
    # A calendar year in a named reporting month is context, not a currency value.
    serialized = json.dumps(computed, default=str)
    for year, month in set(re.findall(r'"([0-9]{4})-([0-9]{2})"', serialized)):
        n = int(month)
        if 1 <= n <= 12:
            summary = re.sub(
                rf"\b(?:{calendar.month_name[n]}|{calendar.month_abbr[n]})\s+{year}\b",
                "",
                summary,
                flags=re.I,
            )
    allowed = numbers(serialized)
    return [
        value
        for value in numbers(summary)
        if not any(math.isclose(value, other, rel_tol=1e-3, abs_tol=1e-4) for other in allowed)
    ]


STOP = set(
    "a an the is are was were be been of in on at to for and or as by with from this that it has have had document policy states according source our their".split()
)


def _terms(text):
    return {token for token in re.findall(r"[a-z]+", text.lower()) if token not in STOP}


def _metrics(computed):
    if isinstance(computed, dict) and computed.get("dataset") == "sales":
        return computed.get("metrics", [])
    return []


def numeric_claim(claim, computed):
    """Bind a numeric/trend assertion to one metric AND the named periods/basis."""
    metrics = [m for m in _metrics(computed) if m["metric"] == claim.get("metric")]
    if len(metrics) != 1:
        return ("unsupported", "missing_metric_binding")
    metric = metrics[0]
    rows = metric["rows"]
    selected = [
        r
        for r in rows
        if (not claim.get("start") or r["month"] >= claim["start"])
        and (not claim.get("end") or r["month"] <= claim["end"])
    ]
    if not selected or any(r["value"] is None for r in selected):
        return ("unsupported", "missing_period_data")
    first, last = selected[0], selected[-1]
    if (claim.get("start") and first["month"] != claim["start"]) or (
        claim.get("end") and last["month"] != claim["end"]
    ):
        return ("unsupported", "incomplete_requested_period")
    if (
        claim.get("metric") == "margin"
        and claim.get("operation") == "total"
        and len(selected) != len(rows)
    ):
        return ("needs_review", "subperiod_margin_requires_weighted_inputs")

    def ordinal(p):
        year, month = map(int, p.split("-"))
        return year * 12 + month

    delta_months = ordinal(last["month"]) - ordinal(first["month"])
    basis = claim.get("basis", "interval")
    if basis == "yoy" and delta_months != 12:
        return ("contradicted", "yoy_requires_12_month_baseline")
    if basis == "mom" and delta_months != 1:
        return ("contradicted", "mom_requires_adjacent_months")
    if basis == "previous_period":
        return ("needs_review", "previous_period_claim_requires_explicit_comparison_binding")
    change = last["value"] - first["value"]
    expected = {
        "change": change,
        "growth": change / first["value"] if first["value"] else None,
        "point": last["value"],
        "total": sum(r["value"] for r in selected)
        if claim.get("metric") != "margin"
        else metric.get("total"),
    }[claim.get("operation", "total")]
    value = claim.get("value")
    if value is not None and (
        expected is None or not math.isclose(value, expected, rel_tol=1e-3, abs_tol=1e-4)
    ):
        return ("contradicted", "value_does_not_match_bound_metric")
    direction = claim.get("direction")
    if direction:
        actual = "increase" if change > 0 else "decrease" if change < 0 else "flat"
        if direction != actual:
            return ("contradicted", "direction_does_not_match_data")
    if value is None and not direction:
        return ("needs_review", "claim_has_no_checkable_value_or_direction")
    return ("supported", "computed_metric_and_periods_match")


def assess_claim(claim, sources, computed=None, effects=None):
    """Conservative support labels. Unknown paraphrases never count as supported."""
    kind = claim.get("kind", "unclassified")
    citations = claim.get("citations", [])
    source_map = {s["id"]: s for s in sources}
    if any(c not in source_map for c in citations):
        return ("unsupported", "unknown_citation")
    if kind in {"numeric", "trend"}:
        status, reason = numeric_claim(claim, computed or {})
        if status == "supported":
            issues = narrative_issues(claim.get("text", ""), computed)
            # Growth percentages and calculated deltas may be derived from bound rows.
            if any(issue != "unsupported_numeric_assertion" for issue in issues):
                return ("contradicted", "claim_wording_conflicts_with_data")
            extra = unsupported_numbers(
                claim.get("text", ""), {"data": computed, "bound_value": claim.get("value")}
            )
            if extra:
                return ("unsupported", "claim_contains_unbound_numbers")
        return status, reason
    if kind == "causal":
        return ("needs_review", "causation_not_established_by_numeric_coincidence")
    if kind == "action":
        receipt = claim.get("receipt")
        if not receipt or not any(
            e.get("receipt") == receipt and e.get("stored") is True for e in (effects or [])
        ):
            return ("unsupported", "missing_committed_action_receipt")
        return ("supported", "committed_effect_receipt")
    quote = claim.get("quote")
    if quote:
        if not citations:
            return ("unsupported", "quote_has_no_citation")
        if any(quote.casefold() not in source_map[c]["text"].casefold() for c in citations):
            return ("unsupported", "quote_not_in_cited_sources")
        if kind == "extractive" and claim["text"].strip().casefold() == quote.strip().casefold():
            return ("supported", "exact_extractive_support")
        if unsupported_numbers(claim["text"], {"quote": quote}):
            return ("unsupported", "number_not_in_cited_quote")
        terms = _terms(claim["text"])
        overlap = terms & _terms(quote)
        if terms and len(overlap) / len(terms) < 0.35:
            return ("unsupported", "citation_topic_mismatch")

        def neg(s):
            return bool(re.search(r"\b(no|not|never|prohibited|forbidden)\b", s, re.I))

        if neg(claim["text"]) != neg(quote):
            return ("needs_review", "possible_negation_mismatch")
    elif kind in {"extractive", "source"}:
        return ("needs_review", "missing_verbatim_support_quote")
    return ("needs_review", "paraphrase_entailment_not_deterministically_proven")


BLANKET_NONE_OVERDUE = re.compile(
    r"\b(?:no|zero|none of the)\s+(?:\w+\s+){0,2}invoices?\s+(?:\w+\s+){0,3}"
    r"(?:overdue|past[- ]due|outstanding)|\b(?:no|zero)\s+(?:overdue|past[- ]due)\b"
    r"|\bnothing\s+(?:is|was)\s+(?:overdue|past[- ]due)|\bnone\s+(?:are|were|is)\s+"
    r"(?:overdue|past[- ]due)|\ball invoices (?:are|were|have been) paid\b",
    re.I,
)
EXCEPTION_PHRASE = re.compile(
    r"\b(?:other|additional|further|besides|except|apart from|aside from)\b", re.I
)


# A read-only finding must never report that it changed something.
COMPLETED_ACTION = re.compile(
    r"\b(?:has|have|had)\s+(?:now\s+)?been\s+(?:successfully\s+)?(?:deleted|wiped|erased|"
    r"reset|removed|cleared|dropped|purged|updated|sent|emailed|exported|saved|stored|created|"
    r"filed)\b|\b(?:were|was)\s+(?:successfully\s+)?(?:deleted|wiped|erased|reset|removed|"
    r"cleared|dropped|purged|emailed|exported)\b",
    re.I,
)


def narrative_issues(text, computed=None, sources=None):
    """Catch high-value misleading patterns even if a model omits structured claims."""
    issues = []
    computed = computed or {}
    sources = sources or []
    if computed and COMPLETED_ACTION.search(text):
        issues.append("unsupported_action_claim")
    if "overdue_rows" in computed:
        rows_by_id = {r["number"].upper(): r for r in computed["rows"]}
        if {s.upper() for s in re.findall(r"\bINV-[0-9]+\b", text, re.I)} - rows_by_id.keys():
            issues.append("unknown_invoice_identifier")
        # Only bind an unambiguous invoice-to-amount phrase. Broader paraphrases
        # still require review, since a paragraph may also state an aggregate.
        bindings = re.finditer(
            r"\b(INV-[0-9]+)\b(?:\s*(?:[:,(]|is|for|has|an?|overdue|unpaid|outstanding|balance|amount|of|due))*\s*\$([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            text,
            re.I,
        )
        for match in bindings:
            row = rows_by_id.get(match[1].upper())
            if row and float(match[2].replace(",", "")) != row["amount"]:
                issues.append("invoice_amount_mismatch")
        for match in re.finditer(r"\b(INV-[0-9]+)\s+is\s+(not\s+)?overdue\b", text, re.I):
            row = rows_by_id.get(match[1].upper())
            if row and (row in computed["overdue_rows"]) != (match[2] is None):
                issues.append("invoice_overdue_status_mismatch")
        # Blanket status statements carry no identifier or amount, so the binding
        # checks above cannot see them. Compare them with the cutoff-filtered rows.
        # "No other invoices are overdue besides INV-001" is a correct exception statement.
        none_overdue = any(
            BLANKET_NONE_OVERDUE.search(sentence) and not EXCEPTION_PHRASE.search(sentence)
            for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text)
        )
        if none_overdue and computed["overdue_rows"]:
            issues.append("invoice_overdue_status_mismatch")
        if unsupported_numbers(text, computed):
            issues.append("unsupported_invoice_number_or_amount")
    if _metrics(computed):
        if unsupported_numbers(text, computed):
            issues.append("unsupported_numeric_assertion")
        for sentence in re.split(r"[.!?\n]+", text):
            lowered = sentence.lower()
            for metric in _metrics(computed):
                if metric["metric"] not in lowered:
                    continue
                change = metric.get("absolute_change")
                if change is None and len(metric.get("rows", [])) >= 2:
                    first, last = metric["rows"][0]["value"], metric["rows"][-1]["value"]
                    if first is not None and last is not None:
                        change = last - first
                if change is not None:
                    if re.search(r"\b(increased|increase|grew|rose)\b", lowered) and change < 0:
                        issues.append("trend_direction_contradiction")
                    if re.search(r"\b(decreased|decrease|fell|declined)\b", lowered) and change > 0:
                        issues.append("trend_direction_contradiction")
                if re.search(r"year.over.year|\byoy\b", lowered):
                    rows = metric.get("rows", [])
                    if (
                        len(rows) < 2
                        or int(rows[-1]["month"][:4]) * 12
                        + int(rows[-1]["month"][-2:])
                        - int(rows[0]["month"][:4]) * 12
                        - int(rows[0]["month"][-2:])
                        < 12
                    ):
                        issues.append("unsupported_yoy_basis")
        if re.search(r"\b(because|caused by|due to|driven by)\b", text, re.I) and not re.search(
            r"\b(not proven|not established|cannot establish|does not establish)\b", text, re.I
        ):
            issues.append("unsupported_causal_attribution")
    return sorted(set(issues))


def assess_finding(finding, sources, computed=None, effects=None):
    rows = []
    for i, claim in enumerate(finding.get("claims", [])):
        status, reason = assess_claim(claim, sources, computed, effects)
        rows.append({"index": i, "status": status, "reason": reason})
    errors = narrative_issues(finding.get("summary", ""), computed, sources)
    if any(c not in {s["id"] for s in sources} for c in finding.get("citations", [])):
        errors.append("unknown_citation")
    errors += [r["reason"] for r in rows if r["status"] in {"unsupported", "contradicted"}]
    if not sources and not computed and not finding.get("insufficient") and finding.get("summary"):
        errors.append("assertion_without_evidence")
    return {
        "claims": rows,
        "errors": sorted(set(errors)),
        "fully_checked": not errors
        and bool(rows)
        and all(r["status"] == "supported" for r in rows),
        "requires_review": bool(errors)
        or not rows
        or any(r["status"] != "supported" for r in rows)
        or finding.get("summary", "").strip()
        not in {c.get("text", "").strip() for c in finding.get("claims", [])},
    }
