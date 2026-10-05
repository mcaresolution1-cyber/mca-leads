"""Colorado Secretary of State UCC open data (Socrata, data.colorado.gov).

Datasets (public domain, updated daily):
  wffy-3uut  filings      fileid, filingdate, transactiontype, documenttype, terminationflag
  4am6-w6u4  collateral   fileid, collateraldescription, additionalcollateraldescription
  8upq-58vz  debtors      fileid, organizationname, firstname, lastname, address1, city, state, zipcode
  ap62-sav4  secured      fileid, organizationname (the funder or its filing agent)

MCA filings are found by their collateral wording ("Future Receipts" etc.),
which catches funders that file through agents such as CSC or CT Corporation.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from datetime import date

import requests

log = logging.getLogger(__name__)

BASE = "https://data.colorado.gov/resource/{}.json"
FILINGS, COLLATERAL, DEBTORS, SECURED = "wffy-3uut", "4am6-w6u4", "8upq-58vz", "ap62-sav4"

# Wording that marks a merchant cash advance (sale of future receivables).
MCA_PATTERNS = re.compile(
    r"future\s+receipts|future\s+receivables|purchased\s+receivables|"
    r"receivables\s+purchase|sale\s+of\s+future|purchase\s+and\s+sale\s+of\s+future|"
    r"merchant\s+cash\s+advance|revenue\s+based\s+financ",
    re.I,
)
# Debtors that matched the wording in testing but are not MCA merchants.
EXCLUDE_DEBTOR = re.compile(
    r"hospital|health\s+(initiatives|centers?)|catholic\s+charities|county\s+of|city\s+of|"
    r"school\s+district|university|ability\s+connection",
    re.I,
)


class Socrata:
    def __init__(self, base: str = BASE, token_env: str = "SOCRATA_APP_TOKEN", page: int = 5000):
        self.s = requests.Session()
        self.base = base
        token = os.getenv(token_env) or os.getenv("SOCRATA_APP_TOKEN")
        if token:
            self.s.headers["X-App-Token"] = token
        self.page = page

    def get(self, dataset: str, params: dict) -> list[dict]:
        """GET all pages of a SoQL query, with retries."""
        rows, offset = [], 0
        while True:
            p = {**params, "$limit": self.page, "$offset": offset}
            for attempt in range(5):
                r = self.s.get(self.base.format(dataset), params=p, timeout=60)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                break
            else:
                r.raise_for_status()
            batch = r.json()
            rows += batch
            if len(batch) < self.page:
                return rows
            offset += self.page


def _in_clause(ids: list[str]) -> str:
    return "fileid in(" + ",".join(f"'{i}'" for i in ids) + ")"


def _by_fileid(api: Socrata, dataset: str, ids: list[str], select: str, chunk: int = 150) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(ids), chunk):
        for row in api.get(dataset, {"$select": select, "$where": _in_clause(ids[i:i + chunk])}):
            out[str(row.get("fileid"))].append(row)
    return out


def fetch(start: date, end: date, api: Socrata | None = None) -> list[dict]:
    """Return MCA filings with filing date in [start, end], one dict per filing."""
    api = api or Socrata()
    filings = api.get(FILINGS, {
        "$select": "fileid,filingdate,lapsedate",
        "$where": (f"filingdate between '{start.isoformat()}T00:00:00' and '{end.isoformat()}T23:59:59' "
                   "AND transactiontype='Initial Filing' AND filingtype='ucc'"),
        "$order": "fileid",
    })
    log.info("Colorado: %d new UCC-1 filings %s..%s", len(filings), start, end)
    if not filings:
        return []
    meta = {str(f["fileid"]): f for f in filings}
    ids = list(meta)

    collateral = _by_fileid(api, COLLATERAL, ids, "fileid,collateraldescription,additionalcollateraldescription")
    mca_ids = []
    for fid in ids:
        text = " ".join((c.get("collateraldescription") or "") + " " + (c.get("additionalcollateraldescription") or "")
                        for c in collateral.get(fid, []))
        if MCA_PATTERNS.search(text):
            mca_ids.append(fid)
    log.info("Colorado: %d filings carry MCA collateral wording", len(mca_ids))
    if not mca_ids:
        return []

    debtors = _by_fileid(api, DEBTORS, mca_ids,
                         "fileid,organizationname,firstname,lastname,address1,city,state,zipcode")
    secured = _by_fileid(api, SECURED, mca_ids, "fileid,organizationname")

    results = []
    for fid in mca_ids:
        orgs = [d for d in debtors.get(fid, []) if d.get("organizationname")]
        people = [d for d in debtors.get(fid, []) if not d.get("organizationname")]
        main = (orgs or people or [{}])[0]
        name = main.get("organizationname") or " ".join(filter(None, [main.get("firstname"), main.get("lastname")]))
        if not name:
            continue
        excluded = bool(EXCLUDE_DEBTOR.search(name))
        results.append({
            "source": "CO SOS UCC",
            "state_filed": "CO",
            "file_id": fid,
            "filing_date": (meta[fid].get("filingdate") or "")[:10],
            "business_name": name,
            "other_names": "; ".join(d["organizationname"] for d in orgs[1:]),
            "owner_name": "; ".join(" ".join(filter(None, [p.get("firstname"), p.get("lastname")])) for p in people),
            "address": main.get("address1", ""),
            "city": (main.get("city") or "").title(),
            "state": main.get("state", ""),
            "zip": main.get("zipcode", ""),
            "mca_evidence": "collateral says future receipts",
            "funder_or_agent": "; ".join(sorted({s.get("organizationname", "") for s in secured.get(fid, [])} - {""})),
            "excluded_reason": "hospital/nonprofit/government" if excluded else "",
        })
    return results
