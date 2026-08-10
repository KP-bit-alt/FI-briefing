#!/usr/bin/env python3
"""
fi_weekly.py  —  G7 Rates Weekly Data Brief (markdown output).

Two data sources, one output:
  1. FRED API  → US rates, credit OAS, cross-asset, FX (automated)
  2. yields.csv → G7 ex-US sovereign yields at 2Y/10Y/30Y (hand-typed weekly)

Output: a clean .md with tables and numbers. No narrative, no commentary.
You read it, form your view, feed it + your judgment to an AI for a PPT.

Run:
  python fi_weekly.py --demo              # offline, sample data, no FRED
  python fi_weekly.py --live              # pull FRED + read yields.csv
  python fi_weekly.py --live --email      # pull, build, email
"""

import argparse
import csv
import datetime as dt
import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from collections import OrderedDict

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ---------------------------------------------------------------------------
# RSS FEEDS — central banks, Treasury, BLS (last 7 days)
# ---------------------------------------------------------------------------
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

RSS_FEEDS = [
    ("Federal Reserve",
     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB",
     "https://www.ecb.europa.eu/rss/press.html"),
    ("Bank of England",
     "https://www.bankofengland.co.uk/rss/news"),
    ("US Treasury",
     "https://home.treasury.gov/system/files/276/treasury_press_rss.xml"),
    ("BLS",
     "https://www.bls.gov/feed/bls_latest.rss"),
]


def pull_rss(days=7):
    """Pull headlines + links from central bank RSS feeds, last `days` days.
    Returns list of {source, title, link, date}. Fail soft per feed."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    items = []
    for source, url in RSS_FEEDS:
        try:
            r = requests.get(url, timeout=15, headers={
                "User-Agent": "FI-Weekly-Brief/1.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            # standard RSS 2.0: channel/item
            for item in root.iter("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                date_el = item.find("pubDate")
                if title_el is None or link_el is None:
                    continue
                title = title_el.text.strip() if title_el.text else ""
                link = link_el.text.strip() if link_el.text else ""
                # parse date — some feeds use RFC 822, some don't
                pub_date = None
                if date_el is not None and date_el.text:
                    try:
                        pub_date = parsedate_to_datetime(date_el.text.strip())
                    except Exception:
                        pass
                # filter to last N days (if date available)
                if pub_date and pub_date < cutoff:
                    continue
                if title and link:
                    items.append({
                        "source": source,
                        "title": title,
                        "link": link,
                        "date": pub_date.strftime("%a %d %b") if pub_date else "",
                    })
            print(f"[ok] {source}: {sum(1 for i in items if i['source']==source)} items")
        except Exception as e:
            print(f"[warn] RSS failed for {source}: {e}")
    # sort by date descending (undated items at the end)
    items.sort(key=lambda x: x["date"] if x["date"] else "", reverse=True)
    return items


def demo_rss():
    """Offline sample headlines."""
    return [
        {"source": "Federal Reserve", "title": "Governor Waller: Outlook for the Economy and Monetary Policy",
         "link": "https://www.federalreserve.gov/newsevents/speech/waller20260807a.htm",
         "date": "Thu 07 Aug"},
        {"source": "Federal Reserve", "title": "Federal Reserve issues FOMC statement",
         "link": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260805a.htm",
         "date": "Tue 05 Aug"},
        {"source": "ECB", "title": "Monetary policy decisions",
         "link": "https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260807.en.html",
         "date": "Thu 07 Aug"},
        {"source": "Bank of England", "title": "MPC holds Bank Rate at 4.50%",
         "link": "https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/august-2026",
         "date": "Thu 07 Aug"},
        {"source": "US Treasury", "title": "Quarterly Refunding Statement of Acting Assistant Secretary for Financial Markets",
         "link": "https://home.treasury.gov/news/press-releases/jy20260806",
         "date": "Wed 06 Aug"},
        {"source": "BLS", "title": "Consumer Price Index — July 2026",
         "link": "https://www.bls.gov/news.release/cpi.nr0.htm",
         "date": "Tue 05 Aug"},
    ]


# ---------------------------------------------------------------------------
# FRED SERIES CONFIG
# ---------------------------------------------------------------------------
RATES = [
    ("UST 3M",       "DGS3MO", "%"),
    ("UST 2Y",       "DGS2",   "%"),
    ("UST 5Y",       "DGS5",   "%"),
    ("UST 10Y",      "DGS10",  "%"),
    ("UST 30Y",      "DGS30",  "%"),
    ("2s10s",        "T10Y2Y", "bp"),
    ("10Y real",     "DFII10", "%"),
    ("5Y B/E infl",  "T5YIE",  "%"),
    ("10Y B/E infl", "T10YIE", "%"),
    ("5Y5Y fwd infl","T5YIFR", "%"),
    ("SOFR",         "SOFR",   "%"),
]

CREDIT = [
    ("IG OAS",  "BAMLC0A0CM",   "bp"),
    ("HY OAS",  "BAMLH0A0HYM2", "bp"),
    ("BB OAS",  "BAMLH0A1HYBB", "bp"),
    ("B OAS",   "BAMLH0A2HYB",  "bp"),
    ("CCC OAS", "BAMLH0A3HYC",  "bp"),
]

CROSS_FRED = [
    ("S&P 500",     "SP500",        "idx"),
    ("VIX",         "VIXCLS",       "idx"),
    ("Brent",       "DCOILBRENTEU", "usd"),
    ("USD (broad)", "DTWEXBGS",     "idx"),
    ("EUR/USD",     "DEXUSEU",      "fx"),
    ("GBP/USD",     "DEXUSUK",      "fx"),
    ("USD/JPY",     "DEXJPUS",      "fx"),
]

# ---------------------------------------------------------------------------
# FRED DATA LAYER
# ---------------------------------------------------------------------------
def fred_series(series_id, api_key, days=45):
    """Fetch last `days` of daily obs from FRED. Fail soft on any error."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start.isoformat(), "observation_end": end.isoformat(),
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[warn] FRED fetch failed for {series_id}: {e}")
        return []
    out = []
    for o in r.json().get("observations", []):
        if o["value"] != ".":
            out.append((dt.date.fromisoformat(o["date"]), float(o["value"])))
    return out


def latest_and_wow(obs):
    """From a sorted list of (date, value), return (current, ~1w_ago)."""
    if not obs:
        return None, None
    obs = sorted(obs)
    cur_date, cur_val = obs[-1]
    target = cur_date - dt.timedelta(days=7)
    ref_val = obs[0][1]
    for d, v in obs:
        if d <= target:
            ref_val = v
    return cur_val, ref_val


def _row(label, cur, ref, unit):
    """Normalise one data point: level as display string, delta always in bp."""
    if cur is None:
        return {"label": label, "level": "n/a", "delta_bp": None, "unit": unit,
                "raw": None, "raw_ref": None}
    if unit == "bp":
        level = f"{cur * 100:.0f}"
        delta = round((cur - ref) * 100) if ref is not None else None
    else:
        level = f"{cur:.2f}"
        delta = round((cur - ref) * 100) if ref is not None else None
    return {"label": label, "level": level, "delta_bp": delta, "unit": unit,
            "raw": cur, "raw_ref": ref}


def pull_live(api_key):
    """Pull US rates + credit from FRED."""
    data = {"rates": [], "credit": [], "asof": dt.date.today().isoformat()}
    for label, sid, unit in RATES:
        cur, ref = latest_and_wow(fred_series(sid, api_key))
        data["rates"].append(_row(label, cur, ref, unit))
    for label, sid, unit in CREDIT:
        cur, ref = latest_and_wow(fred_series(sid, api_key))
        data["credit"].append(_row(label, cur, ref, unit))
    return data


def pull_cross(api_key):
    """Pull cross-asset levels from FRED. FX shows W/W change."""
    rows = []
    for label, sid, kind in CROSS_FRED:
        obs = fred_series(sid, api_key)
        if not obs:
            rows.append({"label": label, "level": "n/a", "delta": None})
            continue
        cur, ref = latest_and_wow(obs)
        if cur is None:
            rows.append({"label": label, "level": "n/a", "delta": None})
            continue
        if kind == "usd":
            level = f"${cur:,.0f}"
        elif kind == "fx":
            level = f"{cur:.2f}"
        else:
            level = f"{cur:,.0f}"
        # W/W change
        if ref is not None:
            if kind == "fx":
                delta = f"{cur - ref:+.2f}"
            elif kind == "idx" and cur > 100:
                delta = f"{cur - ref:+,.0f}"
            else:
                delta = f"{cur - ref:+.1f}"
        else:
            delta = None
        rows.append({"label": label, "level": level, "delta": delta})
    return rows


# ---------------------------------------------------------------------------
# YIELDS.CSV READER
# ---------------------------------------------------------------------------
COUNTRY_ORDER = ["UK Gilt", "Bund", "OAT", "BTP", "JGB", "Canada"]
MATURITY_ORDER = ["2Y", "10Y", "30Y"]


def read_yields_csv(path):
    """Read yields.csv → {market: {maturity: {yield, yield_1w, delta_bp}}}."""
    data = OrderedDict()
    if not os.path.exists(path):
        print(f"[warn] {path} not found — G7 ex-US section will be empty")
        return data
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                market = row["market"].strip()
                mat = row["maturity"].strip()
                tw = float(row["yield"].strip())
                # accept both "yield_1w" and "yield_1w_ago" as the prior-week column
                lw_raw = row.get("yield_1w") or row.get("yield_1w_ago")
                if lw_raw is None:
                    raise KeyError("neither 'yield_1w' nor 'yield_1w_ago' found")
                lw = float(lw_raw.strip())
                delta = round((tw - lw) * 100)
                if market not in data:
                    data[market] = OrderedDict()
                data[market][mat] = {"yield": tw, "yield_1w": lw, "delta_bp": delta}
            except (KeyError, ValueError) as e:
                print(f"[warn] skipping malformed CSV row: {row} ({e})")
    ordered = OrderedDict()
    for c in COUNTRY_ORDER:
        if c in data:
            ordered[c] = data[c]
    for c in data:
        if c not in ordered:
            ordered[c] = data[c]
    return ordered


def get_yield(g7, market, maturity):
    """Safely extract a yield from the g7 dict."""
    try:
        return g7[market][maturity]["yield"]
    except (KeyError, TypeError):
        return None


def compute_spreads(us_rates, g7):
    """Auto-compute G7 cross-market spreads in bp."""
    us = {}
    for r in us_rates:
        if r["raw"] is not None:
            us[r["label"]] = r["raw"]

    spreads = []
    # UST vs Bund at 2Y, 10Y, 30Y
    for mat, us_key in [("2Y", "UST 2Y"), ("10Y", "UST 10Y"), ("30Y", "UST 30Y")]:
        us_val = us.get(us_key)
        g7_val = get_yield(g7, "Bund", mat)
        if us_val is not None and g7_val is not None:
            spreads.append((f"UST-Bund {mat}", round((us_val - g7_val) * 100)))

    # UST-Gilt 10Y
    us_10 = us.get("UST 10Y")
    gilt_10 = get_yield(g7, "UK Gilt", "10Y")
    if us_10 is not None and gilt_10 is not None:
        spreads.append(("UST-Gilt 10Y", round((us_10 - gilt_10) * 100)))

    # OAT-Bund 10Y
    oat = get_yield(g7, "OAT", "10Y")
    bund = get_yield(g7, "Bund", "10Y")
    if oat is not None and bund is not None:
        spreads.append(("OAT-Bund 10Y", round((oat - bund) * 100)))

    # BTP-Bund 10Y
    btp = get_yield(g7, "BTP", "10Y")
    if btp is not None and bund is not None:
        spreads.append(("BTP-Bund 10Y", round((btp - bund) * 100)))

    return spreads


# ---------------------------------------------------------------------------
# DEMO DATA
# ---------------------------------------------------------------------------
def demo_data():
    def R(label, level, dbp, unit, raw=None, raw_ref=None):
        return {"label": label, "level": level, "delta_bp": dbp, "unit": unit,
                "raw": raw, "raw_ref": raw_ref}
    return {
        "asof": "2026-08-09",
        "rates": [
            R("UST 3M",        "3.90",  +8,  "%",  3.90, 3.82),
            R("UST 2Y",        "4.25",  +2,  "%",  4.25, 4.23),
            R("UST 5Y",        "4.40",  +2,  "%",  4.40, 4.38),
            R("UST 10Y",       "4.69",  +1,  "%",  4.69, 4.68),
            R("UST 30Y",       "5.22",  +1,  "%",  5.22, 5.21),
            R("2s10s",         "46",    -1,  "bp",  0.46, 0.47),
            R("10Y real",      "2.43",  +2,  "%",  2.43, 2.41),
            R("5Y B/E infl",   "2.35",  -2,  "%",  2.35, 2.37),
            R("10Y B/E infl",  "2.25",  -3,  "%",  2.25, 2.28),
            R("5Y5Y fwd infl", "2.15",  -4,  "%",  2.15, 2.19),
            R("SOFR",          "3.65",   0,  "%",  3.65, 3.65),
        ],
        "credit": [
            R("IG OAS",  "78",   -2,  "bp", 0.78, 0.80),
            R("HY OAS",  "271",  -13, "bp", 2.71, 2.84),
            R("BB OAS",  "161",  -13, "bp", 1.61, 1.74),
            R("B OAS",   "287",  -12, "bp", 2.87, 2.99),
            R("CCC OAS", "1017", +11, "bp", 10.17, 10.06),
        ],
    }


def demo_g7():
    raw = [
        ("UK Gilt", "2Y", 4.25, 4.20), ("UK Gilt", "10Y", 4.58, 4.50),
        ("UK Gilt", "30Y", 4.92, 4.85),
        ("Bund", "2Y", 2.42, 2.35), ("Bund", "10Y", 2.68, 2.60),
        ("Bund", "30Y", 2.85, 2.78),
        ("OAT", "2Y", 2.65, 2.58), ("OAT", "10Y", 3.32, 3.25),
        ("OAT", "30Y", 3.75, 3.68),
        ("BTP", "2Y", 2.95, 2.88), ("BTP", "10Y", 3.85, 3.78),
        ("BTP", "30Y", 4.45, 4.38),
        ("JGB", "2Y", 0.35, 0.32), ("JGB", "10Y", 1.28, 1.22),
        ("JGB", "30Y", 2.18, 2.12),
        ("Canada", "2Y", 3.15, 3.10), ("Canada", "10Y", 3.45, 3.40),
        ("Canada", "30Y", 3.55, 3.50),
    ]
    data = OrderedDict()
    for mkt, mat, tw, lw in raw:
        if mkt not in data:
            data[mkt] = OrderedDict()
        data[mkt][mat] = {"yield": tw, "yield_1w": lw,
                          "delta_bp": round((tw - lw) * 100)}
    return data


def demo_cross():
    return [
        {"label": "S&P 500",     "level": "7,758", "delta": "+45"},
        {"label": "VIX",         "level": "14",    "delta": "-1.2"},
        {"label": "Brent",       "level": "$89",   "delta": "+$3"},
        {"label": "USD (broad)", "level": "120",    "delta": "-1"},
        {"label": "EUR/USD",     "level": "1.09",   "delta": "+0.01"},
        {"label": "GBP/USD",     "level": "1.28",   "delta": "+0.01"},
        {"label": "USD/JPY",     "level": "147.50", "delta": "-1.20"},
    ]


# ---------------------------------------------------------------------------
# MARKDOWN BUILDER
# ---------------------------------------------------------------------------
def fmt_delta(d):
    if d is None:
        return "—"
    return f"{d:+d}"


def build_md(data, g7, spreads, cross, rss, path):
    asof = dt.date.fromisoformat(data["asof"]).strftime("%A, %d %B %Y")
    L = []
    a = L.append

    # -- HEADER
    a("# G7 Rates Weekly — Data Brief")
    a("")
    a(f"**As of {asof}**")
    a("")

    # -- US RATES
    a("---")
    a("")
    a("## US Rates Dashboard")
    a("")
    a("| Instrument | Level | W/W (bp) |")
    a("|:-----------|------:|---------:|")
    for r in data["rates"]:
        a(f"| {r['label']} | {r['level']} | {fmt_delta(r['delta_bp'])} |")
    a("")

    # -- CURVE SHAPE
    us = {r["label"]: r["raw"] for r in data["rates"] if r["raw"] is not None}
    curve_parts = []
    if "UST 2Y" in us and "UST 10Y" in us:
        curve_parts.append(f"2s10s: {(us['UST 10Y'] - us['UST 2Y']) * 100:+.0f}bp")
    if "UST 2Y" in us and "UST 30Y" in us:
        curve_parts.append(f"2s30s: {(us['UST 30Y'] - us['UST 2Y']) * 100:+.0f}bp")
    if "UST 5Y" in us and "UST 30Y" in us:
        curve_parts.append(f"5s30s: {(us['UST 30Y'] - us['UST 5Y']) * 100:+.0f}bp")
    if curve_parts:
        a(f"**Curve:** {' | '.join(curve_parts)}")
        a("")

    # -- G7 SOVEREIGN YIELDS
    a("---")
    a("")
    a("## G7 Sovereign Yields")
    a("")
    a("| Market | 2Y | 10Y | 30Y | 10Y W/W (bp) |")
    a("|:-------|---:|----:|----:|-------------:|")
    # UST reference row
    ust_2y = us.get("UST 2Y")
    ust_10y = us.get("UST 10Y")
    ust_30y = us.get("UST 30Y")
    ust_10y_d = next((r["delta_bp"] for r in data["rates"]
                      if r["label"] == "UST 10Y"), None)
    if ust_10y is not None:
        a(f"| **UST** | **{ust_2y:.2f}** | **{ust_10y:.2f}** | **{ust_30y:.2f}** "
          f"| **{fmt_delta(ust_10y_d)}** |")
    else:
        a("| **UST** | n/a | n/a | n/a | — |")
    for market, mats in g7.items():
        y2  = f"{mats['2Y']['yield']:.2f}"  if "2Y"  in mats else "—"
        y10 = f"{mats['10Y']['yield']:.2f}" if "10Y" in mats else "—"
        y30 = f"{mats['30Y']['yield']:.2f}" if "30Y" in mats else "—"
        d10 = fmt_delta(mats["10Y"]["delta_bp"]) if "10Y" in mats else "—"
        a(f"| {market} | {y2} | {y10} | {y30} | {d10} |")
    a("")

    # -- G7 SPREADS
    if spreads:
        a("---")
        a("")
        a("## G7 Spreads")
        a("")
        a("| Spread | Level (bp) |")
        a("|:-------|----------:|")
        for label, bp in spreads:
            a(f"| {label} | {bp:+d} |")
        a("")

    # -- US CREDIT
    a("---")
    a("")
    a("## US Credit")
    a("")
    a("| Index | OAS (bp) | W/W (bp) |")
    a("|:------|--------:|---------:|")
    for r in data["credit"]:
        a(f"| {r['label']} | {r['level']} | {fmt_delta(r['delta_bp'])} |")
    a("")

    # -- CROSS-ASSET & FX
    if cross:
        a("---")
        a("")
        a("## Cross-Asset & FX")
        a("")
        a("| Instrument | Level | W/W |")
        a("|:-----------|------:|----:|")
        for c in cross:
            d = c["delta"] if c["delta"] is not None else "—"
            a(f"| {c['label']} | {c['level']} | {d} |")
        a("")

    # -- CENTRAL BANK & DATA RELEASES (last 7 days)
    if rss:
        a("---")
        a("")
        a("## Key Releases (Last 7 Days)")
        a("")
        a("| Date | Source | Headline |")
        a("|:-----|:-------|:---------|")
        for item in rss:
            date = item["date"] if item["date"] else "—"
            a(f"| {date} | {item['source']} | [{item['title']}]({item['link']}) |")
        a("")

    # -- SOURCES
    a("---")
    a("")
    a("## Sources")
    a("")
    a("- [FRED (all series)](https://fred.stlouisfed.org/)")
    a("- [US Treasury par yield curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/)")
    a("- [BLS release calendar](https://www.bls.gov/schedule/news_release/current_month.htm)")
    a("- [Federal Reserve calendar](https://www.federalreserve.gov/newsevents.htm)")
    a("- [Kutman Pamirov — Substack](https://kutman.substack.com)")
    a("")

    # -- FOOTER
    a("---")
    a("")
    a("*Kutman Pamirov | G7 Rates Weekly | Data only — not investment advice*")
    a("")

    md = "\n".join(L)
    with open(path, "w") as f:
        f.write(md)
    return path, md


# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------
def email_briefing(md_path, us_rates):
    msg = EmailMessage()
    today = dt.date.today().strftime("%d %b %Y")
    msg["Subject"] = f"G7 Rates Weekly — {today}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]

    lines = []
    for label in ["UST 2Y", "UST 10Y", "UST 30Y"]:
        r = next((x for x in us_rates if x["label"] == label), None)
        if r:
            lines.append(f"{label}: {r['level']}  ({fmt_delta(r['delta_bp'])}bp w/w)")
    body = "G7 Rates Weekly — key levels:\n\n" + "\n".join(lines) + \
           "\n\nFull data brief attached.\n"
    msg.set_content(body)

    with open(md_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="markdown",
                           filename=os.path.basename(md_path))
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as sv:
        sv.starttls()
        sv.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        sv.send_message(msg)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="G7 Rates Weekly Data Brief")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--out", default="G7_Rates_Weekly.md")
    ap.add_argument("--csv", default="yields.csv")
    args = ap.parse_args()

    if args.live:
        api = os.environ["FRED_API_KEY"]
        data = pull_live(api)
        g7 = read_yields_csv(args.csv)
        cross = pull_cross(api)
        rss = pull_rss(days=7)
    else:
        data = demo_data()
        g7 = demo_g7()
        cross = demo_cross()
        rss = demo_rss()

    spreads = compute_spreads(data["rates"], g7)
    path, md = build_md(data, g7, spreads, cross, rss, args.out)
    print(f"Built {path}")

    if args.email:
        email_briefing(path, data["rates"])
        print(f"Emailed to {os.environ['MAIL_TO']}")


if __name__ == "__main__":
    main()
