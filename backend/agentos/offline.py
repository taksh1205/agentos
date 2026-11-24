"""Bounded language rules for local demos. All dates come from input or workspace records."""

import calendar
import re
from collections import defaultdict

from .models import Claim, Finding

MONTHS = {
    name.lower(): i
    for i in range(1, 13)
    for name in (calendar.month_name[i], calendar.month_abbr[i])
}
PERIOD = re.compile(
    r"\b(?:(?P<iso>\d{4}-\d{2})|(?P<month>" + "|".join(MONTHS) + r")(?:\s+(?P<year>\d{4}))?)\b",
    re.I,
)


def period_bounds(goal, available):
    matches = list(PERIOD.finditer(goal))
    if not matches:
        return None, None
    periods = []
    for match in matches:
        value = match["iso"]
        if not value:
            month = MONTHS[match["month"].lower()]
            if match["year"]:
                value = f"{match['year']}-{month:02d}"
            else:
                candidates = {p for p in available if p.endswith(f"-{month:02d}")}
                if len(candidates) != 1:
                    raise ValueError("Specify the calendar year for the requested month")
                value = candidates.pop()
        periods.append(value)
    if len(matches) == 1:
        prefix = goal[: matches[0].start()].lower().strip()
        if re.search(r"\b(since|from)$", prefix):
            return periods[0], None
        if re.search(r"\b(through|until)$", prefix):
            return None, periods[0]
        return periods[0], periods[0]
    connector = goal[matches[0].end() : matches[1].start()].strip().lower()
    if len(periods) == 2 and connector == "and":

        def ordinal(period):
            year, month = map(int, period.split("-"))
            return year * 12 + month

        if ordinal(periods[1]) - ordinal(periods[0]) == 1:
            return tuple(periods)
    if len(matches) != 2 or connector not in {"to", "through", "until", "–", "-"}:
        raise ValueError("Specify one month or a contiguous reporting interval")
    return tuple(periods)


REPORT_WRITE = re.compile(
    r"\b(?:record|store|save|write|file|compile)\b[^.!?]{0,90}\b(?:report|brief|memo)\b", re.I
)
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
VALUES = {s: i for i, s in enumerate(ONES)}
VALUES.update({s: 10 * i for i, s in enumerate(TENS, 2)})
QUANTITY = re.compile(
    r"(?P<subject>[\w -]{5,140}?)\s+(?:is|shall be|must be)\s+(?P<number>\d+(?:\.\d+)?|"
    + "|".join(VALUES)
    + r")\s+(?P<unit>workers|people|persons|units|days|hours|seats|dollars|minutes)\b(?P<tail>[^.!?\n]*)",
    re.I,
)


def conflicting_limits(hits):
    groups = defaultdict(dict)
    for hit in hits:
        for sentence in re.split(r"[.!?\n]", hit["text"]):
            # Paragraph chunking can join a heading to a capitalized sentence opener.
            clause = re.split(r"\s+(?=The [A-Z])", sentence.strip())[-1]
            match = QUANTITY.fullmatch(clause)
            if not match:
                continue
            tail = match["tail"].strip().lower()
            # Ignore attribution, preserve dates/conditions. Never merge differently dated rules.
            tail = re.sub(r"^according to [^,]+(?:,\s*|$)", "", tail)
            key = (" ".join(match["subject"].lower().split()), match["unit"].lower(), tail)
            number = match["number"].lower()
            value = VALUES[number] if number in VALUES else float(number)
            groups[key][hit["id"]] = (value, hit["source"])
    conflicts = []
    for (subject, unit, _), rows in groups.items():
        if len({v for v, _ in rows.values()}) > 1 and len({s for _, s in rows.values()}) > 1:
            detail = ", ".join(f"{source}: {value:g} {unit}" for value, source in rows.values())
            conflicts.append((f"Sources disagree about {subject} ({detail}).", set(rows)))
    return conflicts


def extractive_finding(question, hits):
    conflicts = conflicting_limits(hits)
    terms = set(re.findall(r"[a-z]{3,}", question.lower()))
    relevant = [(msg, ids) for msg, ids in conflicts if terms & set(msg.lower().split())]
    ids = set().union(*(s for _, s in relevant))
    selected = [h for h in hits if h["id"] in ids] if ids else hits
    missing = []
    for h in selected:
        for match in re.finditer(
            r"(?:does not (?:list|specify|provide)|no information about)\s+(?:an? |the )?([^.!?\n]+)",
            h["text"],
            re.I,
        ):
            topic = set(re.findall(r"[a-z]{3,}", match[1].lower()))
            if topic and topic <= terms:
                missing.append(h["id"])
    if missing:
        selected = [h for h in selected if h["id"] in missing]
    statements = [h["text"][:1450].strip() for h in selected]
    issues = [msg for msg, _ in relevant]
    summary = "\n".join(issues + statements)[:6000] or "Insufficient evidence."
    return Finding(
        summary=summary,
        citations=[h["id"] for h in selected],
        claims=[
            Claim(kind="extractive", text=t, quote=t, citations=[h["id"]])
            for h, t in zip(selected, statements)
            if t
        ],
        insufficient=not selected or bool(missing) or bool(issues),
        contradictions=issues,
    )
