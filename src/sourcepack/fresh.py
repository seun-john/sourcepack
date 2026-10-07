"""Evidence freshness: which sources are due for another look?

Age is checked against the review interval you set. "Due" means "check it again", not
"it is wrong". Nothing here fetches a source or schedules a reminder.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .core import InputError, finding, report, require


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InputError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InputError(f"{field} must be an array of ids")
    return value


def fresh(data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    as_of = _date(data["as_of"], "as_of") if "as_of" in data else (today or date.today())
    sources = require(data, "sources", list)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for source in sources:
        ident = require(source, "id", str)
        if not ident or ident in seen:
            raise InputError("Source ids must be non-empty and unique")
        seen.add(ident)
        claims = _ids(source.get("claim_ids", []), "claim_ids")
        checked, interval = source.get("checked_at"), source.get("review_after_days")
        if not checked or interval is None:
            out.append(
                finding(
                    "NEEDS_REVIEW",
                    "The check date or review interval is missing.",
                    source=ident,
                    affected_claims=claims,
                )
            )
            continue
        if type(interval) is not int or interval < 0:
            raise InputError("review_after_days must be a non-negative integer")
        checked_on = _date(checked, "checked_at")
        age = (as_of - checked_on).days
        if age < 0:
            out.append(
                finding(
                    "INVALID_DATE", "The check date is after the assessment date.", source=ident
                )
            )
            continue
        due = age >= interval
        out.append(
            finding(
                "REVIEW_DUE" if due else "WITHIN_REVIEW_WINDOW",
                "Check this source again." if due else "Still inside the review interval.",
                source=ident,
                checked_at=checked_on.isoformat(),
                age_days=age,
                review_after_days=interval,
                next_review=(checked_on + timedelta(days=interval)).isoformat(),
                affected_claims=claims,
            )
        )
        before, current = source.get("previous_fingerprint"), source.get("current_fingerprint")
        if before is not None and current is not None and before != current:
            out.append(
                finding(
                    "SOURCE_CHANGED",
                    "The source's fingerprint changed; the claims that rely on it need review.",
                    source=ident,
                    affected_claims=claims,
                )
            )
    if not sources:
        out.append(finding("NEEDS_REVIEW", "No evidence sources were supplied."))
    return report(
        "SourcePack Freshness",
        out,
        as_of=as_of.isoformat(),
        scope="your review policy applied to dates you supply; no live retrieval or reminders",
    )
