"""Find a website and a published business email for each lead, at $0 by default.

Free steps (always on):
  1. Website/email: local match against Overture Maps Places (open data, see places.py).
  2. Email: the business's own homepage, /contact and /about pages. Pages that say the
     owner won't share addresses are skipped, and robots.txt is respected.
  3. Check: the email's domain must have a mail server (DNS MX lookup).
Optional, only if you add a key (all have free allowances):
  - SERPER_API_KEY: Google search for websites Overture doesn't know (2,500 free once).
  - HUNTER_API_KEY: Hunter free plan, 50 credits/month, capped by HUNTER_MONTHLY_CAP.
  - MILLIONVERIFIER_API_KEY: mailbox-level verification (100 free credits).
Nothing is guessed: every email comes from a page or a licensed open/commercial dataset.
"""
from __future__ import annotations

import logging
import os
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; mca-leads/1.0; business-contact lookup)"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CFEMAIL_RE = re.compile(r'data-cfemail="([0-9a-fA-F]+)"')
JUNK = re.compile(r"(example\.|sentry|wixpress|@2x|\.png|\.jpg|\.gif|\.webp|\.svg|godaddy|squarespace|"
                  r"domain\.com|yourdomain|email\.com|noreply|no-reply|donotreply)", re.I)
# CAN-SPAM 15 USC 7704(b)(1): don't collect addresses from sites that say they won't share them.
NO_SHARE = re.compile(r"(will\s+not|won't|do\s+not|does\s+not)\s+(sell|share|give|rent|transfer|disclose)"
                      r"[^.]{0,80}e-?mail\s+address", re.I)
DIRECTORY_HOSTS = ("yelp.", "facebook.", "bbb.org", "yellowpages.", "mapquest.", "linkedin.", "instagram.",
                   "tripadvisor.", "opencorporates.", "bizapedia.", "manta.", "dnb.com", "zoominfo.", "buzzfile.",
                   "chamberofcommerce.", "nextdoor.", "doordash.", "grubhub.", "ubereats.", "toasttab.", "google.",
                   "apple.com", "angi.com", "homeadvisor.", "houzz.", "thumbtack.", "indeed.", "glassdoor.",
                   "opengovus.", "bloomberg.", "crunchbase.", "wikipedia.", "procore.", "sos.state", "coloradosos")
CONTACT_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us")
STOP = {"llc", "inc", "corp", "corporation", "co", "ltd", "the", "and", "of", "dba", "company", "pc", "lp", "pllc",
        "services", "group", "enterprises", "holdings"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in STOP and len(t) > 2}


def _is_directory(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(d in host for d in DIRECTORY_HOSTS)


def find_website(name: str, city: str, state: str, s: requests.Session) -> tuple[str, int]:
    """Return (website, match score 0-3). Score: name token in domain/title +1, city in snippet +1, KG +1."""
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return "", 0
    clean = re.sub(r"\b(llc|inc|corp|l\.l\.c\.|ltd)\b\.?|,", "", name, flags=re.I).strip()
    try:
        r = s.post("https://google.serper.dev/search", headers={"X-API-KEY": key},
                   json={"q": f'"{clean}" {city} {state}', "gl": "us", "num": 10}, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        log.warning("Serper failed for %s: %s", name, e)
        return "", 0
    toks = _tokens(clean)
    kg = data.get("knowledgeGraph", {})
    if kg.get("website") and not _is_directory(kg["website"]):
        return kg["website"], 3
    best, best_score = "", 0
    for hit in data.get("organic", []):
        link = hit.get("link", "")
        if not link or _is_directory(link):
            continue
        host = urlparse(link).netloc.lower()
        text = (hit.get("title", "") + " " + hit.get("snippet", "")).lower()
        score = int(any(t in host or t in text for t in toks)) + int(city.lower() in text)
        if score > best_score:
            best, best_score = f"{urlparse(link).scheme}://{urlparse(link).netloc}/", score
    return (best, best_score) if best_score >= 1 else ("", 0)


def _decode_cf(hexstr: str) -> str:
    key = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def _robots_ok(root: str, s: requests.Session) -> urllib.robotparser.RobotFileParser | None:
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = s.get(urljoin(root, "/robots.txt"), headers={"User-Agent": UA}, timeout=10)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def scrape_emails(website: str, s: requests.Session) -> tuple[str, str]:
    """Return (email, page_url) published on the site, preferring the site's own domain."""
    u = urlparse(website)
    root = f"{u.scheme or 'https'}://{u.netloc}"
    domain = u.netloc.lower().removeprefix("www.")
    rp = _robots_ok(root, s)
    found: list[tuple[str, str]] = []
    for path in CONTACT_PATHS:
        url = urljoin(root, path) if path else website
        if rp and not rp.can_fetch(UA, url):
            continue
        try:
            r = s.get(url, headers={"User-Agent": UA}, timeout=20)
        except requests.RequestException:
            continue
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        html = r.text
        if NO_SHARE.search(html):
            log.info("Skipping %s: site says it won't share email addresses", url)
            return "", ""
        candidates = EMAIL_RE.findall(html.replace("[at]", "@").replace("(at)", "@"))
        candidates += [_decode_cf(h) for h in CFEMAIL_RE.findall(html)]
        for e in candidates:
            e = e.strip(".").lower()
            if not JUNK.search(e):
                found.append((e, url))
        if any(e.endswith("@" + domain) for e, _ in found):
            break
        time.sleep(0.5)
    if not found:
        return "", ""
    found.sort(key=lambda x: (not x[0].endswith("@" + domain),
                              not x[0].startswith(("info@", "contact@", "hello@", "office@", "owner@"))))
    return found[0]


def hunter_email(website: str, s: requests.Session) -> tuple[str, str]:
    key = os.getenv("HUNTER_API_KEY")
    if not key or not website:
        return "", ""
    domain = urlparse(website).netloc.removeprefix("www.")
    try:
        r = s.get("https://api.hunter.io/v2/domain-search",
                  params={"domain": domain, "type": "generic", "limit": 10, "api_key": key}, timeout=30)
        r.raise_for_status()
        emails = sorted(r.json().get("data", {}).get("emails", []), key=lambda e: -(e.get("confidence") or 0))
        if emails and (emails[0].get("confidence") or 0) >= 80:
            return emails[0]["value"], f"hunter.io domain search ({emails[0]['confidence']}%)"
    except requests.RequestException as e:
        log.warning("Hunter failed for %s: %s", domain, e)
    return "", ""


def mx_ok(domain: str) -> bool:
    try:
        import dns.resolver
        return bool(dns.resolver.resolve(domain, "MX", lifetime=10))
    except Exception:
        try:
            import dns.resolver
            return bool(dns.resolver.resolve(domain, "A", lifetime=10))
        except Exception:
            return False


def verify(email: str, s: requests.Session) -> str:
    key = os.getenv("MILLIONVERIFIER_API_KEY")
    if not email:
        return ""
    if not mx_ok(email.split("@")[-1]):
        return "invalid"
    if not key:
        return "mx ok"
    try:
        r = s.get("https://api.millionverifier.com/api/v3/", params={"api": key, "email": email, "timeout": 20},
                  timeout=40)
        r.raise_for_status()
        return r.json().get("result", "unknown")      # ok | catch_all | unknown | invalid | disposable
    except requests.RequestException as e:
        log.warning("MillionVerifier failed for %s: %s", email, e)
        return "unknown"


def enrich(leads: list[dict], place_index=None) -> list[dict]:
    from .places import PlaceIndex
    s = requests.Session()
    idx = place_index if place_index is not None else PlaceIndex()
    hunter_left = int(os.getenv("HUNTER_MONTHLY_CAP", "12"))      # ~50/month free plan, run weekly
    for lead in leads:
        for k in ("website", "website_match", "email", "email_source", "email_status"):
            lead.setdefault(k, "")
        if lead.get("excluded_reason"):
            continue
        if not lead["website"]:
            site, email, score = idx.match(lead)
            if site or email:
                lead["website"], lead["website_match"] = site, "overture"
                if email:
                    lead["email"], lead["email_source"] = email.lower(), "Overture Maps places data"
        if not lead["website"]:
            site, score = find_website(lead["business_name"], lead.get("city", ""), lead.get("state", ""), s)
            lead["website"], lead["website_match"] = site, ("high" if score >= 2 else "medium" if score else "")
        if lead["website"] and not lead["email"]:
            lead["email"], lead["email_source"] = scrape_emails(lead["website"], s)
        if lead["website"] and not lead["email"] and hunter_left > 0 and os.getenv("HUNTER_API_KEY"):
            hunter_left -= 1
            lead["email"], lead["email_source"] = hunter_email(lead["website"], s)
        if lead["email"]:
            lead["email_status"] = verify(lead["email"], s)
    return leads
