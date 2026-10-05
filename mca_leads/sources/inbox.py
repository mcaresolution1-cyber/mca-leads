"""Manual drop-in: any CSV placed in inbox/ is merged into the weekly file.

Use it for free data a person downloads by hand, for example California's free weekly UCC
download from bizfileOnline, or results copied from a state search site that does not allow
automated access (NY, NC, GA, MD...). Column names are matched loosely; the minimum is a
business/debtor name. Rows are filtered with the same funder list as the automated states.
Processed files move to inbox/processed/.
"""
from __future__ import annotations

import csv
import logging
import re
import shutil
from datetime import date
from pathlib import Path

from ..funders import FunderList
from .colorado import EXCLUDE_DEBTOR

log = logging.getLogger(__name__)
ALIASES = {
    "business_name": ["business_name", "debtor", "debtor_name", "debtor name", "organization", "name"],
    "address": ["address", "debtor_address", "street", "address1", "debtor address"],
    "city": ["city", "debtor_city"], "state": ["state", "debtor_state", "st"], "zip": ["zip", "zipcode", "postal"],
    "funder_or_agent": ["funder", "secured_party", "secured party", "secured party name", "funder_or_agent"],
    "filing_date": ["filing_date", "filing date", "date filed", "file date"],
    "file_id": ["file_id", "file number", "filing number", "file_number"],
    "state_filed": ["state_filed", "filing state", "jurisdiction"],
    "collateral": ["collateral", "collateral_description"],
}
FUTURE = re.compile(r"future\s+receipts|future\s+receivables|receivables\s+purchase", re.I)


def _pick(row: dict, key: str) -> str:
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for a in ALIASES[key]:
        if low.get(a):
            return str(low[a]).strip()
    return ""


def fetch(start: date, end: date, folder: str | Path = "inbox", funders: FunderList | None = None) -> list[dict]:
    funders = funders or FunderList()
    folder = Path(folder)
    out = []
    for path in sorted(folder.glob("*.csv")):
        state_hint = re.match(r"([A-Za-z]{2})[_\-]", path.name)
        with path.open(newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f)):
                name = _pick(row, "business_name")
                if not name:
                    continue
                funder = _pick(row, "funder_or_agent")
                kind = funders.classify(funder) if funder else "agent"
                coll = _pick(row, "collateral")
                if FUTURE.search(coll):
                    evidence = "collateral says future receipts"
                elif kind == "mca":
                    evidence = "known MCA funder"
                elif kind == "agent":
                    evidence = "filing agent only (possible MCA)" if funder else "manual import (no funder given)"
                else:
                    continue
                st = _pick(row, "state_filed") or (state_hint.group(1).upper() if state_hint else _pick(row, "state"))
                out.append({
                    "source": f"inbox:{path.name}", "state_filed": st, "file_id": _pick(row, "file_id") or f"{path.stem}-{i}",
                    "filing_date": _pick(row, "filing_date"), "business_name": name, "other_names": "", "owner_name": "",
                    "address": _pick(row, "address"), "city": _pick(row, "city").title(), "state": _pick(row, "state"),
                    "zip": _pick(row, "zip"), "funder_or_agent": funder, "mca_evidence": evidence,
                    "excluded_reason": "hospital/nonprofit/government" if EXCLUDE_DEBTOR.search(name) else "",
                })
        done = folder / "processed"
        done.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), done / path.name)
    if out:
        log.info("Inbox: %d rows imported", len(out))
    return out
