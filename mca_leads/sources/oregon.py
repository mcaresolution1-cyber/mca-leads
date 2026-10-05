"""Oregon Secretary of State UCC open data (data.oregon.gov, dataset snfi-f79b).

Free, public domain. "UCC List of Filings Entered Last Month" is replaced once a month, so
new rows appear monthly; the weekly job simply picks them up when they land. One row per
party (party_type DB = debtor, SP = secured party), joined on file_number. No collateral
text, so MCA filings are matched by secured party (funder list or filing agent).
"""
from __future__ import annotations

import logging
from datetime import date

from ..funders import FunderList
from .colorado import EXCLUDE_DEBTOR, Socrata

log = logging.getLogger(__name__)
URL = "https://data.oregon.gov/resource/{}.json"


def fetch(start: date, end: date, api: Socrata | None = None, funders: FunderList | None = None) -> list[dict]:
    api = api or Socrata(base=URL, token_env="OR_SOCRATA_APP_TOKEN")
    funders = funders or FunderList()
    rows = api.get("snfi-f79b", {
        "$where": (f"filing_date between '{start.isoformat()}T00:00:00' and '{end.isoformat()}T23:59:59' "
                   "AND file_type='INITIAL' AND lien_type='UCC'"),
        "$order": "file_number"})
    by_file: dict[str, dict[str, list]] = {}
    for r in rows:
        by_file.setdefault(r["file_number"], {"DB": [], "SP": []}).setdefault(r.get("party_type", ""), []).append(r)
    results = []
    for fid, parts in by_file.items():
        secured = sorted({p.get("entity", "") for p in parts["SP"]} - {""})
        kinds = {funders.classify(s) for s in secured}
        kind = "mca" if "mca" in kinds else "agent" if "agent" in kinds else ""
        orgs = [p for p in parts["DB"] if p.get("entity_type") == "ORG"]
        if not kind or not orgs:
            continue
        main = orgs[0]
        results.append({
            "source": "OR SOS UCC", "state_filed": "OR", "file_id": fid,
            "filing_date": main.get("filing_date", "")[:10], "business_name": main["entity"],
            "other_names": "; ".join(o["entity"] for o in orgs[1:]),
            "owner_name": "; ".join(p["entity"] for p in parts["DB"] if p.get("entity_type") == "IND"),
            "address": " ".join(filter(None, [main.get("mail_addr_1"), main.get("mail_addr_2")])),
            "city": (main.get("city_descr") or "").title(), "state": main.get("st_cd_txt", ""),
            "zip": (main.get("zip_code_txt") or "")[:5], "funder_or_agent": "; ".join(secured),
            "mca_evidence": "known MCA funder" if kind == "mca" else "filing agent only (possible MCA)",
            "excluded_reason": "hospital/nonprofit/government" if EXCLUDE_DEBTOR.search(main["entity"]) else "",
        })
    log.info("Oregon: %d initial filings in window, %d matched a funder or agent", len(by_file), len(results))
    return results
