from datetime import date
from mca_leads.sources import colorado
from mca_leads import run

FILINGS = [{"fileid": "2592871", "filingdate": "2026-09-01T00:00:00.000"},
           {"fileid": "2592872", "filingdate": "2026-09-01T00:00:00.000"},
           {"fileid": "2594243", "filingdate": "2026-09-05T00:00:00.000"},
           {"fileid": "2594402", "filingdate": "2026-09-06T00:00:00.000"}]
COLL = [{"fileid": "2592871", "collateraldescription": "UNKNOWN",
         "additionalcollateraldescription": 'Secured Party has purchased certain "Future Receipts" from Debtor.'},
        {"fileid": "2592872", "collateraldescription": "2019 CAT 320 EXCAVATOR SERIAL 123"},
        {"fileid": "2594243", "additionalcollateraldescription": "all future receipts of the hospital"},
        {"fileid": "2594402", "additionalcollateraldescription": "Purchase and sale of future receivables"}]
DEBT = [{"fileid": "2592871", "organizationname": "STOP4GAS ONE LLC", "address1": "1233 S SHERIDAN BLVD", "city": "LAKEWOOD", "state": "CO", "zipcode": "80232"},
        {"fileid": "2594243", "organizationname": "CATHOLIC HEALTH INITIATIVES COLORADO", "city": "Colorado Springs", "state": "CO"},
        {"fileid": "2594402", "organizationname": "STOP4GAS ONE LLC", "city": "LAKEWOOD", "state": "CO"},
        {"fileid": "2594402", "firstname": "Jane", "lastname": "Doe", "city": "LAKEWOOD", "state": "CO"}]
SEC = [{"fileid": "2592871", "organizationname": "Corporation Service Company, as Representative"}]

class Fake:
    def get(self, ds, params):
        w = params.get("$where", "")
        data = {"wffy-3uut": FILINGS, "4am6-w6u4": COLL, "8upq-58vz": DEBT, "ap62-sav4": SEC}[ds]
        if "fileid in(" in w:
            ids = set(x.strip("'") for x in w.split("in(")[1].rstrip(")").split(","))
            return [r for r in data if r["fileid"] in ids]
        return data

def test_fetch_and_mark():
    leads = colorado.fetch(date(2026, 9, 1), date(2026, 9, 7), api=Fake())
    assert [l["file_id"] for l in leads] == ["2592871", "2594243", "2594402"]   # excavator dropped
    assert leads[0]["funder_or_agent"].startswith("Corporation Service")
    assert leads[1]["excluded_reason"]                                       # hospital excluded
    assert leads[2]["owner_name"] == "Jane Doe"
    marked = run.mark(leads)
    assert [l["status"] for l in marked] == ["Stacked", "Stacked", "Excluded"]

def test_write(tmp_path):
    leads = run.mark(colorado.fetch(date(2026, 9, 1), date(2026, 9, 7), api=Fake()))
    paths = run.write_files(leads, tmp_path, "2026-09-07")
    assert all(p.exists() for p in paths)
