#!/usr/bin/env python3
"""
fi_weekly.py — G7 + EM Rates Weekly Briefing generator.

What it does:
  1. Pulls US rates, credit, and cross-asset data from FRED.
     Computes week-over-week changes in basis points.
  2. Combines with hand-typed G7 ex-US and EM sovereign yields from content.py.
     Auto-computes W/W deltas and key cross-market spreads.
  3. Renders a markdown briefing built for a trader (tape up front) and an
     analyst (themes + positioning in the back).
  4. Optionally emails the markdown as a Sunday attachment.

Run:
  python fi_weekly.py --demo                 # offline sample, no network, no email
  python fi_weekly.py --live                 # pull FRED, build .md, no email
  python fi_weekly.py --live --email         # pull, build, email it

Env vars for --live / --email:
  FRED_API_KEY     free key from https://fred.stlouisfed.org/docs/api/api_key.html
  SMTP_HOST        e.g. smtp.gmail.com
  SMTP_PORT        e.g. 587
  SMTP_USER        sending address
  SMTP_PASS        app password
  MAIL_TO          recipient
"""

import argparse
import datetime as dt
import os
import smtplib
from email.message import EmailMessage

import requests

# The judgment layer — narrative, G7/EM yields, calendar, themes.
import content


# ----------------------------------------------------------------------------
# 1. CONFIG
# ----------------------------------------------------------------------------
BRAND = "Kutman Pamirov  ·  Fixed Income Weekly"
TIMEZONE_LABEL = "Times ET unless noted"

# FRED series: (label, series_id, display_unit)
# "%"  => yield, shown as X.XX%
# "bp" => spread/OAS, shown as Xbp (FRED stores %-pts, so *100)
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

# Cross-asset series pulled from FRED. (label, series_id, prefix)
CROSS_FRED = [
    ("S&P 500",   "SP500",      ""),
    ("Brent",     "DCOILBRENTEU", "$"),
    ("Broad USD", "DTWEXBGS",   ""),
]

# Curated source links
LINKS = [
    ("FRED dashboard (all series live)", "https://fred.stlouisfed.org/"),
    ("US Treasury daily par yield curve", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"),
    ("BLS release calendar (CPI/NFP)", "https://www.bls.gov/schedule/news_release/current_month.htm"),
    ("Federal Reserve calendar / speeches", "https://www.federalreserve.gov/newsevents.htm"),
    ("Kutman Pamirov — Substack", "https://kutman.substack.com"),
]


# ----------------------------------------------------------------------------
# 2. DATA LAYER
# ----------------------------------------------------------------------------
def fred_series(series_id, api_key, days=45):
    """Return list of (date, value) for the last `days`. Fails soft -> []."""
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        out = []
        for o in r.json().get("observations", []):
            if o["value"] != ".":
                out.append((dt.date.fromisoformat(o["date"]), float(o["value"])))
        return out
    except Exception as e:
        print(f"FRED fetch failed for {series_id}: {e}")
        return []


def latest_and_wow(obs):
    """Given [(date,val)...], return (current, ref_1w_ago)."""
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
    """Normalise one line: level shown in native unit, delta always in bp."""
    if cur is None:
        return {"label": label, "level": "n/a", "delta_bp": None,
                "unit": unit, "raw": None, "raw_ref": None}
    if unit == "bp":
        level = f"{cur*100:.0f}"
        delta = round((cur - ref) * 100) if ref is not None else None
    else:
        level = f"{cur:.2f}"
        delta = round((cur - ref) * 100) if ref is not None else None
    return {"label": label, "level": level, "delta_bp": delta,
            "unit": unit, "raw": cur, "raw_ref": ref}


def pull_live(api_key):
    """Build data dict from FRED. Narrative fields are left for content.py."""
    data = {
        "rates": [],
        "credit": [],
        "cross": [],
        "asof": dt.date.today().isoformat(),
    }
    for label, sid, unit in RATES:
        cur, ref = latest_and_wow(fred_series(sid, api_key))
        data["rates"].append(_row(label, cur, ref, unit))
    for label, sid, unit in CREDIT:
        cur, ref = latest_and_wow(fred_series(sid, api_key))
        data["credit"].append(_row(label, cur, ref, unit))
    for label, sid, prefix in CROSS_FRED:
        cur, _ = latest_and_wow(fred_series(sid, api_key))
        if cur is not None:
            if prefix == "$":
                level = f"${cur:.2f}"
            elif label == "S&P 500":
                level = f"{cur:,.2f}"
            else:
                level = f"{cur:.2f}"
            data["cross"].append((label, level))
    return data


# ----------------------------------------------------------------------------
# 3. DEMO DATA
# ----------------------------------------------------------------------------
def demo_data():
    """Sample market data for --demo. Narrative lives in content.py."""
    def R(label, level, dbp, unit, raw=None, raw_ref=None):
        return {"label": label, "level": level, "delta_bp": dbp,
                "unit": unit, "raw": raw, "raw_ref": raw_ref}
    return {
        "asof": "2026-08-07",
        "rates": [
            R("UST 3M",       "4.35",  2, "%", 4.35, 4.33),
            R("UST 2Y",       "4.12",  6, "%", 4.12, 4.06),
            R("UST 5Y",       "4.28",  8, "%", 4.28, 4.20),
            R("UST 10Y",      "4.66",  9, "%", 4.66, 4.57),
            R("UST 30Y",      "5.06", 11, "%", 5.06, 4.95),
            R("2s10s",        "54",    3, "bp", 0.54, 0.51),
            R("10Y real",     "2.05",  6, "%", 2.05, 1.99),
            R("10Y B/E infl", "2.61",  5, "%", 2.61, 2.56),
            R("SOFR",         "4.32",  0, "%", 4.32, 4.32),
        ],
        "credit": [
            R("IG OAS",  "100",  2, "bp", 1.00, 0.98),
            R("HY OAS",  "272",  6, "bp", 2.72, 2.66),
            R("BB OAS",  "175",  4, "bp", 1.75, 1.71),
            R("B OAS",   "320",  7, "bp", 3.20, 3.13),
            R("CCC OAS", "640", 15, "bp", 6.40, 6.25),
        ],
        "cross": [
            ("S&P 500",   "6,550.00"),
            ("Brent",     "$78.00"),
            ("Broad USD", "99.80"),
        ],
    }


# ----------------------------------------------------------------------------
# 4. MARKDOWN BUILDER
# ----------------------------------------------------------------------------
def build_md(data):
    """Assemble the full markdown briefing from FRED data + content.py."""
    asof = dt.date.fromisoformat(data["asof"]).strftime("%A, %d %B %Y")
    week_label = content.WEEK_LABEL
    regime = content.REGIME

    lines = []

    # 1. Title
    lines.append("# G7 + EM Rates Weekly Briefing")
    lines.append("")

    # 2. Meta
    lines.append(f"**{week_label}** · {asof} · *{regime}*")
    lines.append("")

    # 3. The Tape
    lines.append("## The Tape")
    lines.append("")
    for t in content.TAPE:
        lines.append(f"- {t}")
    lines.append("")

    # 4. US Rates Dashboard
    lines.append("## US Rates Dashboard")
    lines.append("")
    lines.append("| | Level | W/W |")
    lines.append("|:---|:---|:---|")
    for r in data["rates"]:
        if r["unit"] == "bp":
            level = f"{r['level']}bp"
        else:
            level = f"{r['level']}%"
        if r["delta_bp"] is None:
            d = "n/a"
        else:
            d = f"{r['delta_bp']:+d}bp"
        lines.append(f"| {r['label']} | {level} | {d} |")
    lines.append("")
    lines.append(f"*{content.RATES_READ}*")
    lines.append("")

    # 5. G7 Sovereign Yields (10Y)
    lines.append("## G7 Sovereign Yields (10Y)")
    lines.append("")
    lines.append("| | Level | W/W |")
    lines.append("|:---|:---|:---|")

    # UST 10Y from FRED
    ust10 = data["rates"][3]  # index 3 = UST 10Y
    ust_level = f"{ust10['level']}%" if ust10["unit"] != "bp" else f"{ust10['level']}bp"
    ust_d = f"{ust10['delta_bp']:+d}bp" if ust10['delta_bp'] is not None else "n/a"
    lines.append(f"| UST 10Y | {ust_level} | {ust_d} |")

    # G7 ex-US from content.py
    g7_map = {}
    for label, this_week, last_week in content.G7_EX_US:
        delta = round((this_week - last_week) * 100)
        g7_map[label] = this_week
        lines.append(f"| {label} | {this_week:.2f}% | {delta:+d}bp |")

    lines.append("")

    # G7 spreads
    spreads_g7 = []
    ust10_raw = ust10["raw"]
    if ust10_raw is not None and "Bund 10Y" in g7_map:
        spreads_g7.append(f"UST-Bund: {round((ust10_raw - g7_map['Bund 10Y']) * 100):+d}bp")
    if ust10_raw is not None and "UK Gilt 10Y" in g7_map:
        spreads_g7.append(f"UST-Gilt: {round((ust10_raw - g7_map['UK Gilt 10Y']) * 100):+d}bp")
    if "OAT 10Y" in g7_map and "Bund 10Y" in g7_map:
        spreads_g7.append(f"OAT-Bund: {round((g7_map['OAT 10Y'] - g7_map['Bund 10Y']) * 100):+d}bp")
    if "BTP 10Y" in g7_map and "Bund 10Y" in g7_map:
        spreads_g7.append(f"BTP-Bund: {round((g7_map['BTP 10Y'] - g7_map['Bund 10Y']) * 100):+d}bp")

    if spreads_g7:
        lines.append("**Key spreads:** " + " · ".join(spreads_g7))
        lines.append("")

    # 6. EM Sovereign Yields (10Y)
    lines.append("## EM Sovereign Yields (10Y)")
    lines.append("")
    lines.append("| | Level | W/W |")
    lines.append("|:---|:---|:---|")

    em_map = {}
    for label, this_week, last_week in content.EM_YIELDS:
        delta = round((this_week - last_week) * 100)
        em_map[label] = this_week
        lines.append(f"| {label} | {this_week:.2f}% | {delta:+d}bp |")

    lines.append("")

    # EM spreads
    spreads_em = []
    if "Greece 10Y" in em_map and "Bund 10Y" in g7_map:
        spreads_em.append(f"Greece-Bund: {round((em_map['Greece 10Y'] - g7_map['Bund 10Y']) * 100):+d}bp")
    if "Hungary 10Y" in em_map and "Bund 10Y" in g7_map:
        spreads_em.append(f"Hungary-Bund: {round((em_map['Hungary 10Y'] - g7_map['Bund 10Y']) * 100):+d}bp")
    if "Poland 10Y" in em_map and "Bund 10Y" in g7_map:
        spreads_em.append(f"Poland-Bund: {round((em_map['Poland 10Y'] - g7_map['Bund 10Y']) * 100):+d}bp")
    if "Turkey 10Y" in em_map and ust10_raw is not None:
        spreads_em.append(f"Turkey-UST: {round((em_map['Turkey 10Y'] - ust10_raw) * 100):+d}bp")
    if "India 10Y" in em_map and ust10_raw is not None:
        spreads_em.append(f"India-UST: {round((em_map['India 10Y'] - ust10_raw) * 100):+d}bp")

    if spreads_em:
        lines.append("**Key spreads:** " + " · ".join(spreads_em))
        lines.append("")

    # 7. US Credit
    lines.append("## US Credit")
    lines.append("")
    lines.append("| | Level | W/W |")
    lines.append("|:---|:---|:---|")
    for r in data["credit"]:
        level = f"{r['level']}bp"
        if r["delta_bp"] is None:
            d = "n/a"
        else:
            d = f"{r['delta_bp']:+d}bp"
        lines.append(f"| {r['label']} | {level} | {d} |")
    lines.append("")
    lines.append(f"*{content.CREDIT_READ}*")
    lines.append("")
    lines.append(content.CARRY_BOX)
    lines.append("")

    # 8. Cross-Asset
    lines.append("## Cross-Asset")
    lines.append("")
    lines.append("| | Level |")
    lines.append("|:---|:---|")
    for label, level in data["cross"]:
        lines.append(f"| {label} | {level} |")
    for label, level in content.CROSS_MANUAL:
        lines.append(f"| {label} | {level} |")
    lines.append("")

    # 9. What Matters This Week
    lines.append("## What Matters This Week")
    lines.append("")
    for i, (head, body, read) in enumerate(content.THEMES, 1):
        lines.append(f"**{i}. {head}**")
        lines.append("")
        lines.append(body)
        lines.append("")
        lines.append(f"*{read}*")
        lines.append("")

    # 10. Week Ahead
    lines.append("## Week Ahead")
    lines.append("")
    lines.append("| Date | Event | Time (ET) | Why It Matters |")
    lines.append("|:---|:---|:---|:---|")
    for date, event, time, why in content.CALENDAR:
        lines.append(f"| {date} | {event} | {time} | {why} |")
    lines.append("")

    # 11. Sources
    lines.append("## Sources")
    lines.append("")
    for label, url in LINKS:
        lines.append(f"- [{label}]({url})")
    lines.append("")

    # 12. Footer
    lines.append("---")
    lines.append("")
    lines.append(f"*{BRAND} | Views are illustrative — not investment advice*")

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 5. EMAIL
# ----------------------------------------------------------------------------
def email_md(path, tape):
    """Email the markdown file. Body = tape bullets for phone readability."""
    msg = EmailMessage()
    today = dt.date.today().strftime("%d %b %Y")
    msg["Subject"] = f"G7 + EM Rates Weekly — {today}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]

    body = "The Tape:\n\n" + "\n\n".join(f"- {t}" for t in tape) + "\n\nFull briefing attached.\n"
    msg.set_content(body)

    with open(path, "r", encoding="utf-8") as f:
        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="plain",
            filename=os.path.basename(path),
        )

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as sv:
        sv.starttls()
        sv.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        sv.send_message(msg)


# ----------------------------------------------------------------------------
# 6. MAIN
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="pull from FRED")
    ap.add_argument("--demo", action="store_true", help="offline sample data")
    ap.add_argument("--email", action="store_true", help="email the briefing")
    ap.add_argument("--out", default="G7_EM_Rates_Weekly.md")
    args = ap.parse_args()

    if args.live:
        data = pull_live(os.environ["FRED_API_KEY"])
    else:
        data = demo_data()

    md = build_md(data)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)

    print("Built", args.out)

    if args.email:
        email_md(args.out, content.TAPE)
        print("Emailed to", os.environ["MAIL_TO"])


if __name__ == "__main__":
    main()
