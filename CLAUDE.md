# CLAUDE.md — project context for Claude Code

## What this is
A self-updating calendar of **public + school holidays for every Australian
state/territory**, built for planning meetings involving people across the
country (Therapeutic Guidelines). It generates subscribable `.ics` files hosted
on GitHub Pages; users subscribe once in Outlook. See `README.md` for full
detail — this file is the quick orientation.

## How it works (one paragraph)
`python -m src.build` gathers public holidays from the `holidays` library
(rule-based, all 8 jurisdictions, national dates deduped to `[National]`) and
school holidays from per-state sources, then writes `.ics` files into `docs/`.
A weekly GitHub Action reruns it and commits changes. Each school source resolves
`live fetch → data/cache (last-known-good) → data/seed/<state>.csv → empty`, so a
broken department page never empties the calendar. Per-run health is written to
`docs/status.json`.

## Data sources
- Public holidays: `src/public_holidays.py` (the `holidays` library).
- School — official `.ics` feeds: QLD, NSW (per-year), TAS.
- School — HTML term-date tables via `base.parse_term_tables`: VIC, WA, SA, ACT, NT.
- Verified seed data checked in: VIC 2026–2028; WA/SA/ACT/NT 2026.

## First tasks (in order)
1. **Push and deploy** (I have the user's git/gh credentials locally):
   - Create the repo if it doesn't exist (`gh repo create aus-holidays-calendar --public --source=. --remote=origin` or ask the user).
   - `git init && git add . && git commit -m "Initial commit" && git branch -M main && git push -u origin main`
   - Set Actions write permission: repo Settings → Actions → General → Workflow permissions → **Read and write** (via `gh api` or tell the user — this is a settings toggle).
   - Enable Pages from branch `main` / folder `/docs` (via `gh api` or tell the user).
   - Trigger the workflow: `gh workflow run "Build calendars"`.
2. **Validate the scrapers.** After the first Actions run, read `docs/status.json`.
   For each state under `school`, `source` should be `live`. Any state showing
   `seed` or `none` means its scraper returned nothing and needs fixing.

## Fixing a broken scraper
- ICS states (QLD/NSW/TAS): check the feed/page URL still resolves; the parser is
  `base.events_from_ics`.
- Table states (VIC/WA/SA/ACT/NT): `base.parse_term_tables` expects a
  `Term | Start | Finish` HTML table with the year in a nearby heading/caption.
  The parser is **verified against VIC's markup**. If another state structures its
  page differently (e.g. a PDF, or "Break" rows instead of term rows), adapt
  `parse_term_tables` or give that state its own `fetch()`. Verify by fetching the
  live page and confirming the derived breaks match the seed for 2026.

## Known soft spots (don't "fix" without checking)
- WA/ACT/NT **summer-break end dates** (return in early 2027) in the seeds are
  provisional; they confirm from the live scrape. Everything else in the seeds is
  verified against official sources.
- `holidays` library covers AFL Grand Final Day and other proclaimed holidays for
  announced years; far-future entries are rule-based estimates. This is expected —
  don't add a second public-holiday source unless a real discrepancy appears.
- DTSTAMP is a fixed constant (`src/config.py`) on purpose, so identical data
  yields byte-identical output and CI commits stay clean. Don't switch it to now().

## Ground rules from the user (Brad)
- Prefers a single evolving reference over scattered files; keep README/CLAUDE.md
  as the source of truth and update them when behaviour changes.
- Wants confirmed vs. estimated data clearly separated. Label directional guesses.
- Direct, concise, copy-paste-ready. One clear recommendation over a menu.

## Local dev
```bash
pip install -r requirements.txt
python -m src.build   # writes docs/*.ics + docs/status.json
```
