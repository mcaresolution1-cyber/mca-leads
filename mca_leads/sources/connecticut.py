"""Connecticut Secretary of the State UCC lien filings (Socrata, data.ct.gov xfev-8smz).

Free, public domain, refreshed nightly. No collateral text, so MCA filings are
found by the secured party name (data/funders.csv) or a filing agent
("as representative"), which is flagged as a possible lead.
Fields: id_ucc_flng_nbr, cd_flng_type ('ORIG FIN STMT' for new filings), tx_lien_descript,
debtor_nm_bus / debtor_nm_first / debtor_nm_last, debtor_ad_str1, debtor_ad_city,
debtor_ad_state, debtor_ad_zip, sec_party_nm_bus, dt_accept, lien_status.
"""
from __future__ import annotations

import logging
from datetime import date

from ..funders import FunderList
from .colorado import EXCLUDE_DEBTOR, Socrata

log = logging.getLogger(__name__)
URL = "https://data.ct.gov/resource/{}.json"


def fetch(start: date, end: date, api: Socrata | None = None, funders: FunderList | None = None) -> list[dict]:
    api = api or Socrata(base=URL, token_env="CT_SOCRATA_APP_TOKEN")
    funders = funders or FunderList()
    rows = api.get("xfev-8smz", {
        "$where": (f"dt_accept between '{start.isoformat()}T00:00:00' and '{end.isoformat()}T23:59:59' "
                   "AND cd_flng_type='ORIG FIN STMT' AND tx_lien_descript='OFS'"),
        "$order": "id_ucc_flng_nbr",
    })
    log.info("Connecticut: %d new financing statements %s..%s", len(rows), start, end)

    by_filing: dict[str, list[dict]] = {}
    for r in rows:
        by_filing.setdefault(r["id_ucc_flng_nbr"], []).append(r)

    results = []
    for fid, parts in by_filing.items():
        secured = sorted({p.get("sec_party_nm_bus", "") for p in parts} - {""})
        kinds = {funders.classify(s) for s in secured}
        kind = "mca" if "mca" in kinds else "agent" if "agent" in kinds else ""
        if not kind:
            continue
        orgs = [p for p in parts if p.get("debtor_nm_bus")]
        people = [p for p in parts if not p.get("debtor_nm_bus") and p.get("debtor_nm_last")]
        if not orgs:
            continue          # individuals with an agent filing are usually consumer/equipment deals
        main = orgs[0]
        name = main["debtor_nm_bus"]
        results.append({
            "source": "CT SOTS UCC",
            "state_filed": "CT",
            "file_id": fid,
            "filing_date": main.get("dt_accept", "")[:10],
            "business_name": name,
            "other_names": "; ".join(sorted({o["debtor_nm_bus"] for o in orgs[1:]} - {name})),
            "owner_name": "; ".join(" ".join(filter(None, [p.get("debtor_nm_first"), p.get("debtor_nm_last")])) for p in people),
            "address": main.get("debtor_ad_str1", ""),
            "city": (main.get("debtor_ad_city") or "").title(),
            "state": main.get("debtor_ad_state", ""),
            "zip": main.get("debtor_ad_zip", ""),
            "funder_or_agent": "; ".join(secured),
            "mca_evidence": "known MCA funder" if kind == "mca" else "filing agent only (possible MCA)",
            "excluded_reason": "hospital/nonprofit/government" if EXCLUDE_DEBTOR.search(name) else "",
        })
    log.info("Connecticut: %d filings matched a funder or filing agent", len(results))
    return results
