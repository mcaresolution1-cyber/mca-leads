from datetime import date
from mca_leads.funders import FunderList
from mca_leads.sources import connecticut
from mca_leads import run

ROWS = [
 {"id_ucc_flng_nbr": "1", "debtor_nm_bus": "SVL LLC", "debtor_ad_city": "Avon", "debtor_ad_state": "CT", "sec_party_nm_bus": "CORPORATION SERVICE COMPANY, as REPRESENTATIVE", "dt_accept": "2026-09-21T00:00:00.000"},
 {"id_ucc_flng_nbr": "2", "debtor_nm_bus": "PIZZA PALACE LLC", "debtor_ad_city": "Hartford", "debtor_ad_state": "CT", "sec_party_nm_bus": "THE LCF GROUP, INC.", "dt_accept": "2026-09-22T00:00:00.000"},
 {"id_ucc_flng_nbr": "3", "debtor_nm_bus": "DIGGERS INC", "sec_party_nm_bus": "Kubota Credit Corporation, U.S.A.", "dt_accept": "2026-09-22T00:00:00.000"},
 {"id_ucc_flng_nbr": "4", "debtor_nm_bus": "ROOF CO", "sec_party_nm_bus": "LEAF Capital Funding, LLC", "dt_accept": "2026-09-22T00:00:00.000"},
 {"id_ucc_flng_nbr": "5", "debtor_nm_last": "ENDO", "debtor_nm_first": "PAULO", "sec_party_nm_bus": "FIRST CORPORATE SOLUTIONS, AS REPRESENTATIVE", "dt_accept": "2026-09-22T00:00:00.000"},
 {"id_ucc_flng_nbr": "6", "debtor_nm_bus": "NEW FUNDER CLIENT LLC", "sec_party_nm_bus": "Acme Revenue Partners LLC", "dt_accept": "2026-09-23T00:00:00.000"},
]
class Fake:
    def get(self, ds, params): return ROWS

def test_ct_filter(tmp_path):
    fl = FunderList("data/funders.csv")
    fl.path = tmp_path / "f.csv"
    assert fl.learn(["Acme Revenue Partners LLC; Corporation Service Company, as Representative"]) == 1
    leads = connecticut.fetch(date(2026, 9, 20), date(2026, 9, 27), api=Fake(), funders=fl)
    names = {l["business_name"]: l["mca_evidence"] for l in leads}
    assert names == {"SVL LLC": "filing agent only (possible MCA)", "PIZZA PALACE LLC": "known MCA funder",
                     "NEW FUNDER CLIENT LLC": "known MCA funder"}       # Kubota, LEAF, individual dropped
    marked = run.mark(leads, suppressed={"svl.com"})
    assert [l["status"] for l in marked][-1] == "Possible"
