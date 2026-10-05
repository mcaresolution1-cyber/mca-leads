"""Free business website/email lookup from Overture Maps Places (no API key, no cost).

Overture publishes ~60M places as open parquet files on a public S3 bucket (CDLA-Permissive-2.0 /
Apache-2.0, commercial use allowed with attribution). Once a month, per state, we extract
name/address/website/email into data/places/<ST>.parquet with DuckDB, then match each lead
locally by name + ZIP/city (+ street number). Attribution: "Contains Overture Maps data".
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BUCKET_LIST = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
# Rough state bounding boxes (lon_min, lon_max, lat_min, lat_max), padded; used to skip most files.
BBOX = {
    "CO": (-109.3, -101.8, 36.8, 41.2), "CT": (-73.9, -71.6, 40.8, 42.2), "RI": (-72.0, -71.0, 41.0, 42.2),
    "OR": (-124.9, -116.2, 41.8, 46.5), "CA": (-124.7, -113.9, 32.3, 42.2), "NY": (-80.0, -71.6, 40.3, 45.2),
    "FL": (-87.9, -79.8, 24.2, 31.2), "TX": (-106.9, -93.3, 25.6, 36.7), "NJ": (-75.8, -73.7, 38.7, 41.6),
    "IL": (-91.8, -86.8, 36.7, 42.7), "PA": (-80.8, -74.5, 39.5, 42.5), "GA": (-85.9, -80.6, 30.1, 35.2),
    "NC": (-84.6, -75.2, 33.6, 36.8), "OH": (-85.1, -80.3, 38.2, 42.2), "MA": (-73.7, -69.7, 41.1, 43.1),
    "MD": (-79.7, -74.9, 37.7, 39.9), "VA": (-83.9, -75.0, 36.4, 39.7), "AZ": (-115.0, -108.9, 31.1, 37.2),
    "WA": (-124.9, -116.7, 45.4, 49.2), "NV": (-120.2, -113.9, 34.8, 42.2), "UT": (-114.3, -108.8, 36.8, 42.2),
    "MI": (-90.6, -82.2, 41.5, 48.5), "IN": (-88.3, -84.6, 37.6, 41.9), "MO": (-95.9, -89.0, 35.8, 40.8),
    "TN": (-90.5, -81.5, 34.8, 36.9), "NM": (-109.3, -102.8, 31.1, 37.2), "VT": (-73.6, -71.3, 42.5, 45.2),
}
SUFFIX = re.compile(r"\b(l\.?l\.?c|inc|corp|corporation|co|company|ltd|limited|pllc|pc|p\.c|lp|llp|the|and|&)\b\.?", re.I)


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", SUFFIX.sub(" ", name.lower()))).strip()


def name_variants(lead: dict) -> list[str]:
    names = [lead.get("business_name", "")] + [n for n in (lead.get("other_names") or "").split(";")]
    out = []
    for n in names:
        for part in re.split(r"\bd\.?b\.?a\.?:?\b", n, flags=re.I):
            p = norm(part)
            if len(p) >= 3 and p not in out:
                out.append(p)
    return out


def latest_release() -> str:
    if os.getenv("OVERTURE_RELEASE"):
        return os.environ["OVERTURE_RELEASE"]
    r = requests.get(BUCKET_LIST, timeout=60)
    r.raise_for_status()
    rel = sorted(re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", r.text))
    if not rel:
        raise RuntimeError("No Overture releases listed")
    return rel[-1]


def build_state(state: str, out: Path, release: str | None = None, source: str | None = None) -> Path:
    """Extract one state's places to parquet (takes a few minutes; run monthly)."""
    import duckdb
    if source is None:
        release = release or latest_release()
        source = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    if source.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    where = ["addresses[1].country = 'US'"]
    if state in BBOX:          # box only: region codes are not reliably filled; matching uses ZIP/city anyway
        x0, x1, y0, y1 = BBOX[state]
        where.insert(0, f"bbox.xmin BETWEEN {x0} AND {x1} AND bbox.ymin BETWEEN {y0} AND {y1}")
    else:
        where.append(f"upper(addresses[1].region) IN ('{state}', 'US-{state}')")
    sql = f"""
      COPY (
        SELECT names.primary AS name, addresses[1].freeform AS street, addresses[1].locality AS city,
               left(addresses[1].postcode, 5) AS zip, websites, emails
        FROM read_parquet('{source}', hive_partitioning=1)
        WHERE {' AND '.join(where)} AND names.primary IS NOT NULL
      ) TO '{out}' (FORMAT parquet)"""
    t = time.time()
    con.execute(sql)
    log.info("Overture %s: built %s from release %s in %.0fs", state, out, release, time.time() - t)
    return out


class PlaceIndex:
    """In-memory index of one or more states' places, keyed by ZIP and city."""

    def __init__(self, folder: str | Path = "data/places", max_age_days: int = 35):
        self.folder, self.max_age = Path(folder), max_age_days * 86400
        self.by_zip: dict[str, list] = {}
        self.by_city: dict[str, list] = {}
        self.loaded: set[str] = set()

    def ensure(self, state: str) -> bool:
        state = state.upper()
        if state in self.loaded:
            return True
        path = self.folder / f"{state}.parquet"
        try:
            if not path.exists() or time.time() - path.stat().st_mtime > self.max_age:
                build_state(state, path)
            import duckdb
            rows = duckdb.connect().execute(f"SELECT name, street, city, zip, websites, emails FROM '{path}'").fetchall()
        except Exception as e:                       # network/S3 problems must not stop the weekly run
            log.warning("Overture places for %s unavailable: %s", state, e)
            self.loaded.add(state)
            return False
        for name, street, city, z, sites, emails in rows:
            rec = (norm(name or ""), (street or "").upper(), sites or [], emails or [])
            if z:
                self.by_zip.setdefault(z, []).append(rec)
            if city:
                self.by_city.setdefault(f"{state}|{city.upper()}", []).append(rec)
        self.loaded.add(state)
        log.info("Overture %s: %d places loaded", state, len(rows))
        return True

    def match(self, lead: dict) -> tuple[str, str, int]:
        """Return (website, email, score) for the best match, or ('', '', 0)."""
        from rapidfuzz import fuzz
        state = (lead.get("state") or "").upper()
        if not state or not self.ensure(state):
            return "", "", 0
        cands = self.by_zip.get((lead.get("zip") or "")[:5]) or \
            self.by_city.get(f"{state}|{(lead.get('city') or '').upper()}", [])
        num = re.match(r"\s*(\d+)", lead.get("address") or "")
        best = ("", "", 0)
        for variant in name_variants(lead):
            vt = set(variant.split())
            for pname, street, sites, emails in cands:
                if not pname:
                    continue
                score = fuzz.token_sort_ratio(variant, pname)
                if len(vt) >= 2 and len(set(pname.split())) >= 2:
                    score = max(score, fuzz.token_set_ratio(variant, pname) - 3)
                if num and street.startswith(num.group(1) + " "):
                    score += 15
                if score > best[2] and (sites or emails):
                    best = (sites[0] if sites else "", emails[0] if emails else "", score)
        return best if best[2] >= 90 else ("", "", 0)
