#!/usr/bin/env python3
"""
Section 10 open-questions checker. Run this from wherever you'll actually
deploy (or just from a normal residential/office network) -- it could NOT
be run successfully from the sandboxed environment this project was built
in, because that environment's outbound IP is blocked by
coloradojudicial.gov's edge WAF (F5/Volterra) even for the plain homepage
and robots.txt, not just the export endpoint. See
docs/DATA_SOURCE_FINDINGS.md for the full writeup of what was and wasn't
reachable during build, and re-run this before trusting
COURT_LOCATION_CODES or the blank-Appearance-Type assumption in production.

Checks:
1. Court location codes (open question #1): fetches the docket search page
   and prints every <option value=...>Label</option> found in any element
   whose surrounding markup mentions "court" or "location", so you can
   confirm the codes in app/config.py:COURT_LOCATION_CODES still point at
   "Boulder County Court" / "Boulder Combined Court" / "Longmont".
2. Appearance Type blank semantics (open question #2): pulls a real export
   for the configured Boulder codes and prints the split of blank vs.
   "IN PERSON" vs. other Appearance Type values, plus a few sample rows of
   each, so a human can judge whether blank rows are actually in-person
   hearings that just don't get the label, or something else (remote,
   unspecified, cancelled).
3. News RSS feed reachability (open question #6): HEAD/GET each configured
   feed and report status + entry count.
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser
import httpx

from app.config import NEWS_RSS_FEEDS
from app.jobs.docket_pull import build_export_url, parse_docket_csv
from datetime import date, timedelta

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}


def check_location_codes():
    print("\n=== 1. Court location codes (coloradojudicial.gov/dockets) ===")
    try:
        resp = httpx.get("https://www.coloradojudicial.gov/dockets", headers=UA, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        print(f"COULD NOT FETCH: {exc}")
        print("-> Re-run this script from an unblocked network, then look for the location <select> "
              "in the page and cross-check against COURT_LOCATION_CODES in app/config.py.")
        return
    options = re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>', resp.text)
    for value, label in options:
        if "boulder" in label.lower() or "longmont" in label.lower():
            print(f"  code={value}  label={label.strip()}")
    if not options:
        print("  No <option value=...> elements found -- the picker may be JS-rendered; "
              "inspect the page manually in a browser and check the network tab for the codes it sends.")


def check_appearance_type():
    print("\n=== 2. Appearance Type blank semantics ===")
    url = build_export_url(date.today(), date.today() + timedelta(days=28))
    try:
        resp = httpx.get(url, headers=UA, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"COULD NOT FETCH: {exc}")
        print("-> Re-run from an unblocked network.")
        return
    rows = parse_docket_csv(resp.text)
    counts = Counter(r.appearance_type.value for r in rows)
    print(f"  {len(rows)} rows. Appearance Type distribution: {dict(counts)}")
    blanks = [r for r in rows if r.appearance_type.value == "unknown"][:5]
    for r in blanks:
        print(f"  BLANK sample: {r.case_number} | {r.hearing_type_raw} | {r.date} | courtroom {r.courtroom}")
    print("  -> Cross-check a few of these case numbers on the public docket search UI to see whether "
          "they show as in-person or remote, then update map_appearance_type() in app/jobs/docket_pull.py "
          "accordingly if blank turns out to reliably mean one or the other.")


def check_rss_feeds():
    print("\n=== 3. News RSS feed reachability ===")
    for name, url in NEWS_RSS_FEEDS.items():
        try:
            resp = httpx.get(url, headers=UA, timeout=15)
            parsed = feedparser.parse(resp.text)
            print(f"  {name}: HTTP {resp.status_code}, {len(parsed.entries)} entries")
        except Exception as exc:
            print(f"  {name}: FAILED ({exc})")


if __name__ == "__main__":
    check_location_codes()
    check_appearance_type()
    check_rss_feeds()
