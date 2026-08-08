"""
content.py  —  THE ONLY FILE YOU EDIT EACH MONDAY (15 minutes).

The engine (fi_weekly.py) pulls every NUMBER from FRED. This file holds every
JUDGMENT — the tape, the themes, the calendar, the positioning reads. Keeping
them apart means:
  - your weekly git commit is just this file (clean history of your calls),
  - the engine never ships last week's narrative over this week's numbers,
  - the 15 minutes you spend here is the part that actually makes you fluent.

Numbers you type here (levels in the prose) are for colour only; the tables and
the curve chart come straight from FRED and will override anything you say.
"""

# Slide 1 — regime tag (short).
REGIME = "Hawkish Fed · bear-steepening · credit tight"

# Slide 1 — "The Tape": the trader's 30-second read. Also the email body.
# 4–6 lines. Lead with the move, then the why, then the positioning.
TAPE = [
    "Bear-steepener: long end led, 30Y ~5.06% near post-2007 highs as a hawkish "
    "Warsh Fed and an oil bounce (Hormuz) revived hike risk into September.",
    "Front end firmer but lagging — market now ~40% for a Sept HIKE (was a cut "
    "debate a month ago). Curve disinverted further; 2s10s ~+54bp.",
    "Credit shrugged: HY OAS ~272bp, IG ~100bp — near multi-decade tights. "
    "Spreads widened only a few bp against a 9bp rates selloff.",
    "Real yields did the work: 10Y real +6bp to ~2.05%; breakevens only +5bp — "
    "this is a real-rate / term-premium move, not a pure inflation scare.",
    "Positioning: carry still pays, but at these spreads the convexity is ugly — "
    "you are short a lot of optionality for ~270bp.",
]

# Slide 2 — one-line read under the curve chart.
RATES_READ = ("Read: the selloff was led by the long end (30Y +11bp vs 2Y +6bp) — "
              "a term-premium / real-rate move, consistent with supply + hike risk "
              "rather than a growth scare.")

# Slide 3 — the analyst "carry trap" box (use \n\n for paragraph breaks).
CARRY_BOX = ("HY index yields ~7.1% — ~$710k of annual carry per $10m.\n\n"
             "But spread duration ≈ 3.2y. A move from 272 → 380bp (a 2023-'tight' "
             "level) marks the book down ~3.5%, ~$320k — five months of carry gone.\n\n"
             "Upside from here: maybe 40bp of compression. That asymmetry is the "
             "whole game at tight spreads.")

# Slide 3 — the positioning line.
CREDIT_READ = ("Positioning: up-in-quality within HY, own the BB over the CCC — the "
               "CCC-BB gap is priced for a soft landing that a hiking Fed threatens.")

# Slide 3 — cross-asset. Leave as [] to auto-pull the FRED-able ones (SP500,
# Brent, broad USD). Anything FRED can't give (MOVE, gold) you add by hand here;
# hand-typed rows are appended after the auto-pulled ones.
CROSS = [
    ("Gold", "$3,450"),
    ("MOVE (rate vol)", "95"),
]

# Slide 4 — three themes: (headline, body, positioning read).
THEMES = [
    ("Hawkish repricing has further to run",
     "The whole front end is priced off one question: does Warsh hike in Sept? "
     "With core CPI sticky and oil rebounding, the risk is asymmetric toward MORE "
     "hikes, not fewer.",
     "Read: stay short duration / underweight the belly; fade rallies in 2Y."),
    ("Credit is the complacent asset",
     "HY at ~272bp with spread duration ~3.2y: a move back to 380bp (a 'tight' "
     "level as recently as 2023) marks a 10Y HY book down ~3.5% — roughly five "
     "months of carry gone. Downside dwarfs the remaining ~40bp of compression.",
     "Read: up-in-quality within HY (BB over CCC); the CCC-BB gap is too thin."),
    ("Oil is the inflation swing factor",
     "Strait of Hormuz headlines are now the marginal driver of breakevens and "
     "the long end. Energy is doing what a data surprise used to do.",
     "Read: watch Brent as a real-time proxy for the September Fed decision."),
]

# Slide 5 — week ahead: (date, event, time, why it matters).
CALENDAR = [
    ("Wed Aug 12", "US CPI (Jul)",         "8:30",  "The print that decides Sept. Core is the number."),
    ("Thu Aug 13", "Germany ZEW · UK jobs", "—",     "EGB / Gilt tone-setter for the week."),
    ("Thu Aug 14", "UK CPI (Jul)",          "2:00",  "BoE path; Gilt-Bund spread."),
    ("Fri Aug 15", "US Retail Sales, Claims","8:30", "Growth check into a hawkish Fed."),
    ("Fri Aug 15", "Michigan sentiment (P)", "10:00","5-10y inflation expectations watched."),
    ("Sep 16",     "FOMC decision + SEP",   "14:00", "The main event this cycle."),
]
