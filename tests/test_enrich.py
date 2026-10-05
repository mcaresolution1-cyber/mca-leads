from mca_leads.enrich import scrape_emails

class R:
    def __init__(self, text, code=200):
        self.text, self.status_code, self.headers = text, code, {"content-type": "text/html; charset=utf-8"}

class S:
    pages = {
        "https://danahercryo.com/": '<a href="/contact-danaher-cryo/">Contact</a><img src="logo@2x.png">',
        "https://danahercryo.com/contact": '<p>Write to <a href="mailto:charlie@danahercryo.com">charlie@danahercryo.com</a> or test@wixpress.com</p>',
    }
    def get(self, url, **kw):
        return R(self.pages.get(url, ""), 200 if url in self.pages else 404)

def test_scrape_prefers_own_domain():
    email, page = scrape_emails("https://danahercryo.com/", S())
    assert email == "charlie@danahercryo.com"
    assert page.endswith("/contact")

from mca_leads.enrich import _decode_cf
from mca_leads import run

class S2(S):
    pages = {"https://shy.com/": '<p>We will not sell or share your email address with anyone.</p> info@shy.com'}

def test_no_share_notice_respected():
    assert scrape_emails("https://shy.com/", S2()) == ("", "")

def test_cloudflare_decode():
    key = 0x42
    enc = "%02x" % key + "".join("%02x" % (ord(c) ^ key) for c in "a@b.co")
    assert _decode_cf(enc) == "a@b.co"

def test_suppression():
    leads = [{"business_name": "X", "email": "info@x.com", "email_status": "ok"}]
    assert run.mark(leads, {"x.com"})[0]["status"] == "Suppressed"
