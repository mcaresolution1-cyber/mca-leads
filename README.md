# MCA Leads: weekly UCC lead file at $0

Every Monday, GitHub Actions (free) pulls new UCC filings from every state whose data is free and allowed to be read automatically. It keeps the filings that look like merchant cash advances, finds each business's website and published email using free sources, and delivers an Excel/CSV file.

## Coverage (50-state survey, October 2026)

| How | States | Notes |
| --- | --- | --- |
| **Automated, free** | Colorado, Connecticut, Rhode Island, Oregon | Official open data (CO, CT, OR) or a free public search with no bot block (RI). Oregon publishes monthly. |
| **Free, but you download it** (drop the CSV in `inbox/`) | California | The SOS fee schedule lists the weekly UCC data download as free. Sign in at bizfileonline.sos.ca.gov → Data Requests → UCC Bulk Order once to set it up. Call (916) 653-3516 if the option isn't offered. |
| **Free to search by hand only** (results can also go in `inbox/`) | NY, NC, GA, MD, MA, VA, OK, HI, DC | These sites ban bots, block robots.txt, or sit behind Cloudflare. A person may search them, for example by secured party "Corporation Service Company", and paste the results into a CSV. |
| **Might be automatable, needs a check from a US connection** | IN, NM, VT, WA, OH, MO, WV | Free search by secured party and/or date exists, but the pages blocked our check (403 or JavaScript-only). Each needs one look in a browser from the US before a module can be written. |
| **Not free** | NJ, PA, DE, FL, SC, TN, TX, LA, AR, AZ, NV, UT, ID, IL, WI, MI, MN, KS, NE, IA, SD, ND, MT, WY, KY, AL, MS, NH, ME | Paid per search, subscription, or debtor-name-only search, which can't find new filings. |
| Left out on purpose | Alaska | Free date search, but protected by DataDome bot blocking; we don't get around that. |

Expect roughly a few hundred new MCA merchants a month from the automated states (mostly Colorado and Connecticut), plus whatever you add through `inbox/`.

## How MCA filings are spotted
- **Colorado and Rhode Island**: the collateral text says "future receipts" or similar (strongest signal).
- **Every state**: the secured party is on `data/funders.csv` (known MCA funders), or is a filing agent filing "as Representative" (CSC, CT Corporation, First Corporate Solutions, Middesk, TAH Services). Agent-only matches are marked **Possible**, because banks use those agents too.
- `data/funders.csv` learns: each funder seen on a Colorado "future receipts" filing is added automatically. Lines marked `ignore` (equipment lenders, banks, SBA, tax) are never leads.

## How websites and emails are found ($0)
1. **Overture Maps Places**: free open data with tens of millions of US businesses, including websites and some emails. Once a month the job extracts each needed state and matches businesses locally by name, ZIP/city and street number. No API key is needed.
2. **The business's own website**: the homepage, /contact and /about pages are read for a published email. robots.txt is respected, and sites that say they won't share addresses are skipped.
3. **Mail server check**: the email's domain must accept mail (DNS MX lookup).

Optional add-ons, each $0 on its free allowance, used only if you add the key:
- Serper: 2,500 free Google searches, one time.
- Hunter: 50 a month free (capped at 12 a week).
- MillionVerifier: 100 free mailbox checks.

Expect a usable email for roughly 20–30% of merchants with the free stack. Many small merchants only have a Facebook page or no site at all.

## Output (`output/`, also emailed if set up)
`mca_leads_YYYY-MM-DD.xlsx` has three sheets: **Ready to email**, **All leads**, and **About** (sources and attribution). A CSV copy is saved alongside it.

Status values:
- **Stacked**: 2+ MCA filings this run.
- **Lead**
- **Possible**: check before sending.
- **Suppressed**: on your opt-out list.
- **Excluded**: hospitals, nonprofits and government bodies.

`data/seen.csv` makes sure no filing is delivered twice.

## One-time setup (about 15 minutes, all free)
1. Create a **private** GitHub repository and upload this folder. Private matters because the lead data is saved in it. Private repos get 2,000 free Actions minutes a month, and this job uses roughly 60–150.
2. Optional but recommended: get a free app token at data.colorado.gov (Sign in → Developer settings), then add it under repo **Settings → Secrets and variables → Actions** as `SOCRATA_APP_TOKEN`.
3. Optional: to get the file by email, add `SMTP_HOST`=smtp.gmail.com, `SMTP_PORT`=587, `SMTP_USER`=your Gmail address, `SMTP_PASSWORD`=a Google *app password*, and `REPORT_TO`=where to send it.
4. Go to the **Actions** tab → **Weekly MCA leads** → **Run workflow**. The first run takes longer while it builds the monthly places data. After that it runs every Monday at 08:17 Pakistan time.

## Adding data by hand (`inbox/`)
Put a CSV in `inbox/` with a name starting with the filing state, e.g. `CA_2026-10-05.csv`. The columns can be any of: Debtor Name, Address, City, State, Zip, Secured Party Name, Filing Date, File Number, Collateral. The next run filters it with the funder list, finds emails, and moves the file to `inbox/processed/`.

## Opt-outs
Add every unsubscribe to `data/suppression.csv` (header `email_or_domain`). CAN-SPAM requires honoring opt-outs within 10 business days.

## Compliance notes (not legal advice)
- Every cold email needs:
  - an accurate sender and subject
  - an ad disclosure
  - your postal address
  - a working unsubscribe link
- Don't imply the email comes from the funder or a court, and don't promise results.
- A UCC filing doesn't prove a balance is owed. Say "public records show a filing".
- Never point automation at the "manual only" sites. Their terms or robots rules forbid it.
- Have a lawyer check debt-relief and referral-fee rules before scaling.

## Run on your own computer
```
pip install -r requirements.txt
python -m mca_leads.run --days 10 --states CO,CT,RI,OR
```
