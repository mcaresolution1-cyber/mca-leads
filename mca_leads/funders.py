"""Funder name list used to spot MCA filings where collateral text is not published (e.g. Connecticut).

data/funders.csv columns: pattern, type, note
  type = mca    -> secured party is a known MCA / revenue-based funder (confident lead)
  type = agent  -> filing agent used by many MCA funders but also by banks (possible lead)
  type = ignore -> never a lead (equipment lessors etc. that match a broad word)
The list learns: every run adds the secured parties on Colorado "future receipts" filings.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

AGENT_RE = re.compile(r"as\s+representative|corporation\s+service\s+company|c\s*t\s+corporation|"
                      r"first\s+corporate\s+solutions|middesk", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


class FunderList:
    def __init__(self, path: str | Path = "data/funders.csv"):
        self.path = Path(path)
        self.rows: list[dict] = []
        if self.path.exists():
            with self.path.open() as f:
                self.rows = list(csv.DictReader(f))

    def classify(self, secured_party: str) -> str:
        """Return 'mca', 'agent' or '' for a secured party name."""
        n = _norm(secured_party)
        for r in self.rows:
            if r["type"] == "ignore" and _norm(r["pattern"]) in n:
                return ""
        for r in self.rows:
            if r["type"] == "mca" and _norm(r["pattern"]) in n:
                return "mca"
        if AGENT_RE.search(secured_party):
            return "agent"
        return ""

    def learn(self, names: list[str]) -> int:
        """Add MCA funders seen on Colorado future-receipts filings. Returns how many were new."""
        known = {_norm(r["pattern"]) for r in self.rows}
        added = 0
        for name in names:
            for part in name.split(";"):
                part = part.strip()
                if not part or AGENT_RE.search(part):
                    continue
                key = _norm(re.sub(r",?\s*(llc|inc|corp|corporation|l\.l\.c\.|co)\.?$", "", part, flags=re.I))
                if len(key) < 4 or key in known:
                    continue
                self.rows.append({"pattern": key, "type": "mca", "note": "learned from CO future-receipts filing"})
                known.add(key)
                added += 1
        return added

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["pattern", "type", "note"])
            w.writeheader()
            w.writerows(self.rows)
