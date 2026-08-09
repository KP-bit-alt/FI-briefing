#!/usr/bin/env python3
"""
fi_weekly.py  —  G7 Rates Weekly Data Brief (markdown output).

Two data sources, one output:
  1. FRED API  → US rates, credit OAS, cross-asset (automated)
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
    ("10Y B/E infl", "T10YIE", "%"),
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
    ("Brent",       "DCOILBRENTEU", "usd"),
    ("USD (broad)", "DTWEXBGS",     "idx"),
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
    """Pull cross-asset levels from FRED (spot only, no W/W)."""
    rows = []
    for label, sid, kind in CROSS_FRED:
        obs = fred_series(sid, api_key)
        if obs:
            v = sorted(obs)[-1][1]
            rows.append((label, f"${v:,.0f}" if kind == "usd" else f"{v:,.0f}"))
    return rows


# ---------------------------------------------------------------------------
# YIELDS.CSV READER
# ---------------------------------------------------------------------------
# Expected CSV columns: market, maturity, yield, yield_1w
# Example row:          Bund, 10Y, 2.68, 2.60
#
# COUNTRY_ORDER controls display order in the G7 table.
COUNTRY_ORDER = ["UK Gilt", "Bund", "OAT", "BTP", "JGB", "Canada"]
MATURITY_ORDER = ["2Y", "10Y", "30Y"]


def read_yields_csv(path):
    """Read yields.csv, return {market: {maturity: {yield, yield_1w, delta_bp}}}."""
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
                lw = float(row["yield_1w"].strip())
                delta = round((tw - lw) * 100)
                if market not in data:
                    data[market] = OrderedDict()
                data[market][mat] = {"yield": tw, "yield_1w": lw, "delta_bp": delta}
            except (KeyError, ValueError) as e:
                print(f"[warn] skipping malformed CSV row: {row} ({e})")
    # re-sort by COUNTRY_ORDER so display is consistent
    ordered = OrderedDict()
    for c in COUNTRY_ORDER:
        if c in data:
            ordered[c] = data[c]
    # append any unexpected countries at the end
    for c in data:
        if c not in ordered:
            ordered[c] = data[c]
    return ordered


def get_yield(g7, market, maturity):
    """Safely extract a yield from the g7 dict. Returns None if missing."""
    try:
        return g7[market][maturity]["yield"]
    except (KeyError, TypeError):
        return None


def compute_spreads(us_rates, g7):
    """Auto-compute G7 cross-market spreads in bp."""
    # extract US yields by label
    us = {}
    for r in us_rates:
        if r["raw"] is not None:
            us[r["label"]] = r["raw"]

    spreads = []

    # UST-Bund at 2Y, 10Y, 30Y
    pairs = [("UST-Bund 2Y",  "UST 2Y",  "Bund",  "2Y"),
             ("UST-Bund 10Y", "UST 10Y", "Bund",  "10Y"),
             ("UST-Bund 30Y", "UST 30Y", "Bund",  "30Y"),
             ("UST-Gilt 10Y", "UST 10Y", "UK Gilt","10Y"),
             ("OAT-Bund 10Y", None,      None,     None),   # special
             ("BTP-Bund 10Y", None,      None,     None)]   # special

    for label, us_key, g7_mkt, mat in pairs[:4]:
        us_val = us.get(us_key)
        g7_val = get_yield(g7, g7_mkt, mat)
        if us_val is not None and g7_val is not None:
            spreads.append((label, round((us_val - g7_val) * 100)))

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
    """Offline sample data — realistic ~Aug 2026 levels."""
    def R(label, level, dbp, unit, raw=None, raw_ref=None):
        return {"label": label, "level": level, "delta_bp": dbp, "unit": unit,
                "raw": raw, "raw_ref": raw_ref}
    return {
        "asof": "2026-08-07",
        "rates": [
            R("UST 3M",       "4.35",  +2,  "%",  4.35, 4.33),
            R("UST 2Y",       "4.12",  +6,  "%",  4.12, 4.06),
            R("UST 5Y",       "4.28",  +8,  "%",  4.28, 4.20),
            R("UST 10Y",      "4.66",  +9,  "%",  4.66, 4.57),
            R("UST 30Y",      "5.06",  +11, "%",  5.06, 4.95),
            R("2s10s",        "+54",   +3,  "bp",  0.54, 0.51),
            R("10Y real",     "2.05",  +6,  "%",  2.05, 1.99),
            R("10Y B/E infl", "2.61",  +5,  "%",  2.61, 2.56),
            R("SOFR",         "4.32",   0,  "%",  4.32, 4.32),
        ],
        "credit": [
            R("IG OAS",  "100", +2,  "bp", 1.00, 0.98),
            R("HY OAS",  "272", +6,  "bp", 2.72, 2.66),
            R("BB OAS",  "175", +4,  "bp", 1.75, 1.71),
            R("B OAS",   "320", +7,  "bp", 3.20, 3.13),
            R("CCC OAS", "640", +15, "bp", 6.40, 6.25),
        ],
    }


def demo_g7():
    """Offline G7 ex-US — same shape as read_yields_csv output."""
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
        data[mkt][mat] = {"yield": tw, "yield_1w": lw, "delta_bp": round((tw - lw) * 100)}
    return data


def demo_cross():
    return [("S&P 500", "6,550"), ("Brent", "$78"), ("USD (broad)", "121")]


# ---------------------------------------------------------------------------
# MARKDOWN BUILDER
# ---------------------------------------------------------------------------
def fmt_delta(d):
    if d is None:
        return "—"
    return f"{d:+d}"


def build_md(data, g7, spreads, cross, path):
    """Build the data-only markdown briefing."""
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

    # -- CURVE SHAPE (auto-computed)
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
    # UST at the top for reference
    ust_2y  = us.get("UST 2Y",  "—")
    ust_10y = us.get("UST 10Y", "—")
    ust_30y = us.get("UST 30Y", "—")
    ust_10y_delta = next((r["delta_bp"] for r in data["rates"]
                          if r["label"] == "UST 10Y"), None)
    a(f"| **UST** | **{ust_2y:.2f}** | **{ust_10y:.2f}** | **{ust_30y:.2f}** "
      f"| **{fmt_delta(ust_10y_delta)}** |"
      if isinstance(ust_10y, float)
      else f"| **UST** | {ust_2y} | {ust_10y} | {ust_30y} | — |")
    # G7 ex-US from CSV
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

    # -- CROSS-ASSET
    if cross:
        a("---")
        a("")
        a("## Cross-Asset")
        a("")
        a("| Instrument | Level |")
        a("|:-----------|------:|")
        for label, val in cross:
            a(f"| {label} | {val} |")
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
    """Email with a 3-line phone summary in the body, full .md attached."""
    msg = EmailMessage()
    today = dt.date.today().strftime("%d %b %Y")
    msg["Subject"] = f"G7 Rates Weekly — {today}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]

    # phone-readable body: just the 3 key US yields + W/W
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
    ap.add_argument("--live", action="store_true", help="pull FRED + read yields.csv")
    ap.add_argument("--demo", action="store_true", help="offline with sample data")
    ap.add_argument("--email", action="store_true", help="email the result")
    ap.add_argument("--out", default="G7_Rates_Weekly.md", help="output filename")
    ap.add_argument("--csv", default="yields.csv", help="path to yields.csv")
    args = ap.parse_args()

    if args.live:
        api = os.environ["FRED_API_KEY"]
        data = pull_live(api)
        g7 = read_yields_csv(args.csv)
        cross = pull_cross(api)
    else:
        data = demo_data()
        g7 = demo_g7()
        cross = demo_cross()

    spreads = compute_spreads(data["rates"], g7)
    path, md = build_md(data, g7, spreads, cross, args.out)
    print(f"Built {path}")

    if args.email:
        email_briefing(path, data["rates"])
        print(f"Emailed to {os.environ['MAIL_TO']}")


if __name__ == "__main__":
    main()
