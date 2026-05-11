"""
test_23800CE_5may26.py
──────────────────────
Diagnostic: how many days can we actually scrape for NIFTY 23800 CE (expiry 5-May-2026)?

ROOT CAUSE FIX:
  Breeze API silently caps every response at ~1000 rows.
  1-min data = ~375 rows/day  →  1000 ÷ 375 ≈ 2.7 days max per call.
  Old code used CHUNK_DAYS=30, so only the last 2-3 days of each window came back.
  FIX: CHUNK_DAYS=1 — one API call per calendar day — guarantees full coverage.

Output:
  - Console + log: per-day row count, first/last bar time, missing-915 warnings
  - CSV: test_NIFTY05MAY2623800CE.csv  (Zerodha-style)

Usage:
  1. Paste fresh SESSION_TOKEN below (or set env var BREEZE_SESSION_TOKEN)
  2. python test_23800CE_5may26.py
"""

import os
import sys
import logging
import datetime as dt
import time
from zoneinfo import ZoneInfo

import pandas as pd
from breeze_connect import BreezeConnect

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG — update SESSION_TOKEN before running
# ──────────────────────────────────────────────────────────────────────────────
API_KEY       = os.getenv("BREEZE_API_KEY",       "536iWS@16)J67_e9717191`8Y1A1%I93")
API_SECRET    = os.getenv("BREEZE_API_SECRET",    "0757h4608s0551135488a47vp817093g")
SESSION_TOKEN = os.getenv("BREEZE_SESSION_TOKEN", "55588126")   # <-- paste token here

EXPIRY_DATE   = dt.date(2026, 5, 5)
STRIKE_PRICE  = 23800
RIGHT         = "call"    # CE
INTERVAL      = "1minute"

# How far back to search (increase if you want more history)
SEARCH_START  = dt.date(2026, 3, 1)    # ~45 trading days before expiry

# KEY FIX: 1 day per API call so we never hit the ~1000-row cap mid-window
CHUNK_DAYS    = 1

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

OUT_CSV = "test_NIFTY05MAY2623800CE.csv"
LOG_FILE = "test_23800CE_5may26.log"

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING — ASCII only to avoid Windows cp1252 errors
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def expiry_iso(d: dt.date) -> str:
    """15:30 IST on expiry day -> UTC ISO string (what Breeze expects)."""
    ist = dt.datetime.combine(d, dt.time(15, 30), tzinfo=IST)
    utc = ist.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def make_chunks(start: dt.date, end: dt.date, days: int):
    """
    Return list of (from_str, to_str) in IST local format.
    Each window is `days` calendar days wide (use days=1 for full daily coverage).
    """
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=days - 1), end)
        frm_ist = dt.datetime.combine(cur,       dt.time(9, 15),      tzinfo=IST)
        to_ist  = dt.datetime.combine(chunk_end, dt.time(15, 30),     tzinfo=IST)
        chunks.append((
            frm_ist.strftime("%Y-%m-%d %H:%M:%S"),
            to_ist.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        cur = chunk_end + dt.timedelta(days=1)
    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    if SESSION_TOKEN == "UPDATE_ME":
        log.error("SESSION_TOKEN is not set! Edit the script or set env var BREEZE_SESSION_TOKEN.")
        sys.exit(1)

    ticker     = f"NIFTY{EXPIRY_DATE.strftime('%d%b%y').upper()}{STRIKE_PRICE}CE"
    expiry_str = expiry_iso(EXPIRY_DATE)
    chunks     = make_chunks(SEARCH_START, EXPIRY_DATE, CHUNK_DAYS)

    log.info("=" * 65)
    log.info("  DIAGNOSTIC: %s", ticker)
    log.info("  Expiry      : %s", EXPIRY_DATE)
    log.info("  Expiry ISO  : %s", expiry_str)
    log.info("  Search from : %s  to  %s", SEARCH_START, EXPIRY_DATE)
    log.info("  Chunk size  : %d day(s) per API call  [FIX: was 30]", CHUNK_DAYS)
    log.info("  Total chunks: %d", len(chunks))
    log.info("=" * 65)

    log.info("Connecting to Breeze API ...")
    breeze = BreezeConnect(api_key=API_KEY)
    breeze.generate_session(api_secret=API_SECRET, session_token=SESSION_TOKEN)
    log.info("Session OK.")

    all_rows = []
    empty_chunks = []
    data_chunks  = []

    for idx, (frm, to) in enumerate(chunks, 1):
        log.info("Chunk %03d/%03d  |  %s  ->  %s", idx, len(chunks), frm, to)

        try:
            resp = breeze.get_historical_data_v2(
                interval      = INTERVAL,
                from_date     = frm,
                to_date       = to,
                stock_code    = "NIFTY",
                exchange_code = "NFO",
                product_type  = "options",
                expiry_date   = expiry_str,
                right         = RIGHT,
                strike_price  = str(STRIKE_PRICE),
            )
        except Exception as e:
            log.warning("  [!] Exception: %s — skipping chunk", e)
            empty_chunks.append(frm[:10])
            time.sleep(1)
            continue

        status = resp.get("Status")
        rows   = resp.get("Success") or []

        if status != 200 or not rows:
            err = resp.get("Error") or resp.get("Message") or "no data"
            log.info("  Status=%s  rows=0  (%s)", status, err)
            empty_chunks.append(frm[:10])
        else:
            log.info("  Status=%s  rows=%d  first=%s  last=%s",
                     status, len(rows),
                     rows[0].get("datetime", "?"),
                     rows[-1].get("datetime", "?"))
            data_chunks.append(frm[:10])
            all_rows.extend(rows)

        # Small polite delay — Breeze allows ~100 req/min; 1 req/day = ~67 chunks max
        time.sleep(0.7)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=" * 65)
    log.info("FETCH COMPLETE")
    log.info("  Total chunks sent : %d", len(chunks))
    log.info("  Chunks with data  : %d", len(data_chunks))
    log.info("  Empty chunks      : %d", len(empty_chunks))
    log.info("  Raw rows collected: %d", len(all_rows))

    if not all_rows:
        log.warning("NO DATA at all — check token / strike / expiry.")
        return

    df = pd.DataFrame(all_rows)
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates(subset=["datetime"])
    df["Date"] = df["datetime"].dt.date
    df["Time"] = df["datetime"].dt.strftime("%H:%M:%S")

    trading_days = sorted(df["Date"].unique())
    log.info("  Trading days found: %d", len(trading_days))
    log.info("")
    log.info("  --- Per-day breakdown ---")

    missing_915 = []
    for day in trading_days:
        grp = df[df["Date"] == day]
        times = set(grp["Time"].tolist())
        has_open = "09:15:00" in times
        flag = "" if has_open else "  [MISSING 09:15]"
        log.info("  %s  |  %d rows  |  %s -> %s%s",
                 day, len(grp),
                 grp["Time"].iloc[0], grp["Time"].iloc[-1],
                 flag)
        if not has_open:
            missing_915.append(day)

    log.info("")
    log.info("  --- Coverage summary ---")
    log.info("  First day : %s", trading_days[0])
    log.info("  Last day  : %s", trading_days[-1])
    log.info("  Days with full open (09:15): %d / %d",
             len(trading_days) - len(missing_915), len(trading_days))

    if missing_915:
        log.warning("  Days missing 09:15 bar: %s", [str(d) for d in missing_915])

    log.info("")
    log.info("  --- What CHUNK_DAYS=30 (old code) would have returned ---")
    log.info("  Each 30-day API call caps at ~1000 rows = ~2.7 days of data.")
    log.info("  You had %d chunks of 30 days, so only the last 2-3 days per chunk came back.",
             -(-len(chunks) // 30))  # ceiling div approximation
    log.info("  With CHUNK_DAYS=1 (this script) you get ALL %d days.", len(trading_days))

    # ── Save CSV ──────────────────────────────────────────────────────────────
    oi_col = next((c for c in ("open_interest", "oi") if c in df.columns), None)
    df["Open Interest"] = df[oi_col] if oi_col else 0
    df = df.rename(columns={"open": "Open", "high": "High",
                             "low": "Low", "close": "Close", "volume": "Volume"})
    df["Ticker"]      = ticker
    df["Expiry Date"] = EXPIRY_DATE.strftime("%Y-%m-%d")
    df["Date_str"]    = df["datetime"].dt.strftime("%Y-%m-%d")
    df["Time_str"]    = df["datetime"].dt.strftime("%H:%M:%S")

    out_cols = ["Ticker", "Date_str", "Time_str", "Expiry Date",
                "Open", "High", "Low", "Close", "Volume", "Open Interest"]
    out_cols = [c for c in out_cols if c in df.columns]
    df[out_cols].to_csv(OUT_CSV, index=False)

    log.info("")
    log.info("  Saved: %s  (%d rows)", OUT_CSV, len(df))
    log.info("  Log : %s", LOG_FILE)
    log.info("=" * 65)


if __name__ == "__main__":
    main()
