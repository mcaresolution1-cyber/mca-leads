import duckdb, os, time
from mca_leads import places

def make_overture(path):
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT * FROM (VALUES
      ({{'primary': 'Danaher Cryo'}}, [{{'freeform': '4699 NAUTILUS CT S', 'locality': 'Boulder', 'postcode': '80301-1234', 'region': 'CO', 'country': 'US'}}],
       ['https://danahercryo.com/'], ['charlie@danahercryo.com'], {{'xmin': -105.2, 'xmax': -105.2, 'ymin': 40.0, 'ymax': 40.0}}),
      ({{'primary': 'Maple Blues Coffee'}}, [{{'freeform': '466 Yampa Ave', 'locality': 'Craig', 'postcode': '81625', 'region': 'CO', 'country': 'US'}}],
       ['https://maplebluescoffee.com/'], NULL, {{'xmin': -107.5, 'xmax': -107.5, 'ymin': 40.5, 'ymax': 40.5}}),
      ({{'primary': 'Danaher Plumbing'}}, [{{'freeform': '1 Main St', 'locality': 'Boulder', 'postcode': '80301', 'region': 'CO', 'country': 'US'}}],
       ['https://wrong.example/'], NULL, {{'xmin': -105.2, 'xmax': -105.2, 'ymin': 40.0, 'ymax': 40.0}}),
      ({{'primary': 'Outside Box'}}, [{{'freeform': '1 Main', 'locality': 'Paris', 'postcode': '75001', 'region': 'IDF', 'country': 'FR'}}],
       ['https://fr.example/'], NULL, {{'xmin': 2.3, 'xmax': 2.3, 'ymin': 48.8, 'ymax': 48.8}})
    ) t(names, addresses, websites, emails, bbox)) TO '{path}' (FORMAT parquet)""")

def test_build_and_match(tmp_path):
    src = tmp_path / "overture.parquet"; make_overture(src)
    out = tmp_path / "places" / "CO.parquet"
    places.build_state("CO", out, source=str(src))
    assert duckdb.connect().execute(f"SELECT count(*) FROM '{out}'").fetchone()[0] == 3   # France row dropped
    idx = places.PlaceIndex(tmp_path / "places")
    site, email, score = idx.match({"business_name": "DANAHER CRYOGENICS LTD", "state": "CO", "zip": "80301",
                                    "city": "Boulder", "address": "4699 NAUTILUS CT S #403"})
    assert (site, email) == ("https://danahercryo.com/", "charlie@danahercryo.com")
    assert idx.match({"business_name": "Maple Blues Coffee", "state": "CO", "zip": "81625", "city": "Craig", "address": ""})[0] == "https://maplebluescoffee.com/"
    assert idx.match({"business_name": "Boulder Tile LLC", "state": "CO", "zip": "80301", "city": "Boulder", "address": "9 Elm"})[2] == 0

def test_name_variants():
    assert places.name_variants({"business_name": "R&B INC DBA: CURRY N KEBOB", "other_names": ""}) == ["r b", "curry n kebob"]
