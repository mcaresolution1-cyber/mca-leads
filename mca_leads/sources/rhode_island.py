"""Rhode Island Department of State free UCC search (business.sos.ri.gov).

No login, CAPTCHA, robots.txt or fee (checked Oct 2026). The search accepts a secured-party
name plus "this date and later", so each run searches every filing agent and known MCA
funder for filings since the start date, then opens each UCC-1 for the debtor and the
collateral text shown on the filing page. Requests are slow and identified.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from html import unescape

import requests

from ..funders import FunderList
from .colorado import EXCLUDE_DEBTOR

log = logging.getLogger(__name__)
BASE = "https://business.sos.ri.gov/CorpWeb/UCCSearch/"
UA = "Mozilla/5.0 (compatible; mca-leads/1.0; public UCC research)"
AGENTS = ["CORPORATION SERVICE", "C T CORPORATION", "CT CORPORATION", "FIRST CORPORATE SOLUTIONS",
          "MIDDESK", "TAH SERVICES"]
FUTURE = re.compile(r"future\s+receipts|future\s+receivables|receivables\s+purchase|sale\s+of\s+future", re.I)
ROW = re.compile(r"<tr class=\"Grid(?:Alt)?Row\">(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG = re.compile(r"<[^>]+>")
DELAY = 1.5


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", html))).strip()


def _results_url(name: str, start: date) -> str:
    q = requests.models.RequestEncodingMixin._encode_params({
        "SearchLapsed": "False", "rdoSearch": "O", "txtLast": "", "txtFirst": "", "txtMiddle": "", "txtSuffix": "",
        "txtICity": "", "txtIState": "", "txtName": name, "txtOCity": "", "txtOState": "", "txtFilingNumber": "",
        "txtStartDate": start.strftime("%m/%d/%Y"), "UCCSearchMethod": "B", "chkDebtor": "",
        "chkSecuredParty": "S", "chkAssignee": "", "lstDisplay": "10000"})
    return BASE + "UCCSearchResults.aspx?" + q


def parse_results(html: str) -> list[dict]:
    out = []
    for row in ROW.findall(html):
        cells = CELL.findall(row)
        if len(cells) < 8:
            continue
        link = re.search(r'href="(UCCFilingHistory\.aspx\?[^"]+)"', row)
        out.append({"secured_party": _text(cells[0]), "filing_type": _text(cells[4]),
                    "file_id": _text(cells[5]), "filing_date": _text(cells[7]),
                    "history": unescape(link.group(1)) if link else ""})
    return out


SECTION = re.compile(r">\s*(Debtor\(s\)|Secured Parties)\s*</td>\s*</tr>\s*<tr>(.*?)</tr>", re.S)
TEXTAREA = re.compile(r"<textarea[^>]*>(.*?)</textarea>", re.S)


def _party(cell_html: str) -> dict | None:
    parts = [unescape(TAG.sub("", p)).strip() for p in re.split(r"<br\s*/?>", cell_html)]
    parts = [p for p in parts if p and p != "\xa0"]
    if not parts:
        return None
    m = re.match(r"(.+?)\s+([A-Z]{2})\s+(\d{5})", parts[-1]) if len(parts) >= 2 else None
    return {"name": parts[0], "address": " ".join(parts[1:-1]) if m else " ".join(parts[1:]),
            "city": m.group(1).title() if m else "", "state": m.group(2) if m else "", "zip": m.group(3) if m else ""}


def parse_history(html: str) -> dict:
    """Debtors (name/street/city/state/zip), secured parties and collateral text from a filing-history page."""
    out = {"debtors": [], "secured": [], "collateral": ""}
    for title, row in SECTION.findall(html):
        parties = [p for p in (_party(c) for c in CELL.findall(row)) if p]
        out["debtors" if title.startswith("Debtor") else "secured"] += parties
    m = TEXTAREA.search(html)
    out["collateral"] = unescape(m.group(1)).strip() if m else ""
    return out


def fetch(start: date, end: date, funders: FunderList | None = None, session: requests.Session | None = None) -> list[dict]:
    funders = funders or FunderList()
    s = session or requests.Session()
    s.headers["User-Agent"] = UA
    names = AGENTS + sorted({r["pattern"].upper() for r in funders.rows if r["type"] == "mca"})
    found: dict[str, dict] = {}
    for name in names:
        url = _results_url(name, start)
        try:
            r = s.get(url, timeout=60)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("RI search failed for %s: %s", name, e)
            continue
        for hit in parse_results(r.text):
            if hit["filing_type"].startswith("UCC-1") and hit["file_id"] not in found:
                hit["results_url"] = url
                found[hit["file_id"]] = hit
        time.sleep(DELAY)
    log.info("Rhode Island: %d UCC-1 filings by agents/funders since %s", len(found), start)

    results = []
    for fid, hit in found.items():
        try:
            r = s.get(BASE + hit["history"], headers={"Referer": hit["results_url"]}, timeout=60)
            r.raise_for_status()
            detail = parse_history(r.text)
        except requests.RequestException as e:
            log.warning("RI detail failed for %s: %s", fid, e)
            continue
        time.sleep(DELAY)
        orgs = [d for d in detail["debtors"] if not EXCLUDE_DEBTOR.search(d["name"])]
        if not orgs:
            continue
        if FUTURE.search(detail["collateral"]):
            evidence = "collateral says future receipts"
        elif funders.classify(hit["secured_party"]) == "mca":
            evidence = "known MCA funder"
        else:
            evidence = "filing agent only (possible MCA)"
        main = orgs[0]
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", hit["filing_date"])
        results.append({
            "source": "RI DOS UCC", "state_filed": "RI", "file_id": fid,
            "filing_date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else hit["filing_date"],
            "business_name": main["name"], "other_names": "; ".join(d["name"] for d in orgs[1:]), "owner_name": "",
            "address": main["address"], "city": main["city"], "state": main["state"], "zip": main["zip"],
            "funder_or_agent": hit["secured_party"], "mca_evidence": evidence, "excluded_reason": "",
        })
    return results
