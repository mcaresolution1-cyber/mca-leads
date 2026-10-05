from datetime import date
from pathlib import Path
from mca_leads.sources import rhode_island as ri
from mca_leads.funders import FunderList

FX = Path(__file__).parent / "fixtures"
RES, HIST = (FX / "ri_results.html").read_text(), (FX / "ri_history.html").read_text()

def test_parse_results():
    rows = ri.parse_results(RES)
    assert [r["filing_type"] for r in rows] == ["UCC-3 TERMINATION", "UCC-1"]
    assert rows[1]["file_id"] == "202634780370" and rows[1]["history"].endswith("UCC1=443943")

def test_parse_history():
    d = ri.parse_history(HIST)
    assert d["debtors"] == [{"name": "MY HOME CARE, LLC", "address": "500 BROAD ST", "city": "Central Falls", "state": "RI", "zip": "02863"}]
    assert d["secured"][0]["name"].startswith("CORPORATION SERVICE")
    assert "Future Receipts" in d["collateral"]

class R:
    def __init__(self, t): self.text, self.status_code = t, 200
    def raise_for_status(self): pass

class S:
    headers = {}
    def __init__(self): self.calls = []
    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return R(HIST if "FilingHistory" in url else RES if "CORPORATION+SERVICE" in url else "")

def test_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DELAY", 0)
    fl = FunderList(tmp_path / "none.csv")
    s = S()
    leads = ri.fetch(date(2026, 9, 28), date(2026, 10, 5), funders=fl, session=s)
    assert len(leads) == 1
    l = leads[0]
    assert (l["business_name"], l["filing_date"], l["mca_evidence"]) == ("MY HOME CARE, LLC", "2026-09-28", "collateral says future receipts")
    detail_call = [c for c in s.calls if "FilingHistory" in c[0]][0]
    assert "UCCSearchResults" in detail_call[1]["Referer"]     # session/referer needed by the site
