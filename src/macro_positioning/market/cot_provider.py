"""CFTC Commitments of Traders (COT) data provider.

Downloads the legacy 'Futures Only' COT report from the CFTC and returns
structured speculative-positioning readings for key markets.

Data source: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
Updated each Tuesday for the prior Friday's report date.  Free, no API key.

Non-Commercial net = Long - Short — the standard speculative positioning proxy.
Positive = speculators are net long; negative = net short.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# CFTC Disaggregated Futures Only — current year, updated weekly.
# URL pattern confirmed 2026-05: https://www.cftc.gov/files/dea/history/fut_disagg_txt_{YEAR}.zip
COT_PRIMARY_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
# Fallback: prior year (for Jan/Feb when current year file may be sparse)
COT_FALLBACK_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

COT_CACHE_MAX_AGE_HOURS = 24  # report is weekly; refresh at most once per day


def _cache_path() -> Path:
    return settings.base_dir / "data" / "cot_cache.zip"


# ---------------------------------------------------------------------------
# Market definitions  — (label, [substrings to match in CFTC name, case-insensitive])
# Market names verified against fut_disagg_txt_2026.zip (2026-05).
# ---------------------------------------------------------------------------

_MARKETS: list[tuple[str, list[str]]] = [
    # Disaggregated report: NYMEX WTI Financial Crude is the main contract
    ("Crude Oil (WTI)",  ["WTI FINANCIAL CRUDE OIL", "CRUDE OIL, LIGHT SWEET"]),
    # Gold: "GOLD - COMMODITY EXCHANGE INC." (disagg drops "100 TROY OUNCES")
    ("Gold",             ["GOLD - COMMODITY EXCHANGE"]),
    # Nat gas: NYMEX contract
    ("Natural Gas",      ["NAT GAS NYME", "NATURAL GAS (HENRY HUB)", "HENRY HUB PENULTIMATE"]),
    ("Corn",             ["CORN - CHICAGO BOARD OF TRADE"]),
    ("Soybeans",         ["SOYBEANS - CHICAGO BOARD OF TRADE"]),
    ("Copper",           ["COPPER- #1"]),
    ("Silver",           ["SILVER - COMMODITY EXCHANGE"]),
    ("Wheat",            ["WHEAT-SRW - CHICAGO BOARD"]),
    # Financial instruments (available in TFF report; included for forward-compat)
    ("Bitcoin",          ["BITCOIN"]),
    ("S&P 500",          ["S&P 500 STOCK INDEX"]),
    ("EUR/USD",          ["EURO FX"]),
    ("JPY/USD",          ["JAPANESE YEN"]),
    ("10Y Treasury",     ["10-YEAR U.S. TREASURY NOTES"]),
    ("2Y Treasury",      ["2-YEAR U.S. TREASURY NOTES"]),
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CotWeeklyReading(BaseModel):
    """One week's COT reading for a single market."""
    market: str          # normalized label (e.g. "Crude Oil (WTI)")
    cftc_name: str       # original CFTC market name
    report_date: date
    noncomm_long: int
    noncomm_short: int
    noncomm_net: int     # long - short (positive = speculators net long)
    open_interest: int
    net_pct_oi: float    # noncomm_net / open_interest * 100


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _is_cache_fresh() -> bool:
    path = _cache_path()
    if not path.exists():
        return False
    age_s = datetime.now(UTC).timestamp() - path.stat().st_mtime
    return age_s < COT_CACHE_MAX_AGE_HOURS * 3600


def _download(url: str) -> bytes:
    logger.info("Downloading COT data from %s", url)
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _get_zip_bytes() -> bytes:
    """Return ZIP bytes from disk cache or fresh download."""
    if _is_cache_fresh():
        return _cache_path().read_bytes()

    year = datetime.now(UTC).year
    try:
        data = _download(COT_PRIMARY_URL.format(year=year))
    except Exception as e:
        logger.warning("COT primary URL failed (%s); trying prior year fallback", e)
        data = _download(COT_FALLBACK_URL.format(year=year - 1))

    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_report_date(row: dict) -> date | None:
    """Try multiple CFTC date column formats.

    Disaggregated format uses:
      As_of_Date_In_Form_YYMMDD  (capital 'In')  → YYMMDD e.g. "260505"
      Report_Date_as_YYYY-MM-DD                  → ISO e.g. "2026-05-05"
    Legacy format uses:
      As_of_Date_in_Form_YYMMDD  (lower 'in')
      Report_Date_as_MM_DD_YYYY
    """
    candidates = [
        ("As_of_Date_In_Form_YYMMDD", "%y%m%d"),   # disaggregated
        ("As_of_Date_in_Form_YYMMDD", "%y%m%d"),   # legacy
        ("Report_Date_as_YYYY-MM-DD", "%Y-%m-%d"),  # disaggregated
        ("Report_Date_as_MM_DD_YYYY", "%m/%d/%Y"),  # legacy
    ]
    for col, fmt in candidates:
        raw = row.get(col, "").strip()
        if not raw:
            continue
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _match_market(cftc_name: str) -> str | None:
    upper = cftc_name.upper()
    for label, patterns in _MARKETS:
        if any(p.upper() in upper for p in patterns):
            return label
    return None


def _int_col(row: dict, *keys: str) -> int:
    for k in keys:
        raw = row.get(k, "").replace(",", "").strip()
        if raw:
            try:
                return int(float(raw))
            except ValueError:
                pass
    return 0


def _parse_rows(csv_text: str) -> list[CotWeeklyReading]:
    reader = csv.DictReader(io.StringIO(csv_text))
    out: list[CotWeeklyReading] = []

    for row in reader:
        cftc_name = row.get("Market_and_Exchange_Names", "").strip()
        market = _match_market(cftc_name)
        if market is None:
            continue

        report_date = _parse_report_date(row)
        if report_date is None:
            continue

        # Disaggregated: Managed Money = speculative proxy
        # Legacy: Non-Commercial = speculative proxy
        nc_long = _int_col(
            row,
            "M_Money_Positions_Long_All",          # disaggregated (preferred)
            "Noncommercial_Positions_Long_All",    # legacy fallback
        )
        nc_short = _int_col(
            row,
            "M_Money_Positions_Short_All",
            "Noncommercial_Positions_Short_All",
        )
        oi = _int_col(row, "Open_Interest_All")
        if oi <= 0:
            continue

        nc_net = nc_long - nc_short
        out.append(CotWeeklyReading(
            market=market,
            cftc_name=cftc_name,
            report_date=report_date,
            noncomm_long=nc_long,
            noncomm_short=nc_short,
            noncomm_net=nc_net,
            open_interest=oi,
            net_pct_oi=round((nc_net / oi) * 100.0, 2),
        ))

    return out


def _extract_csv(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        txt_files = [n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))]
        if not txt_files:
            raise ValueError(f"No .txt/.csv in ZIP; found: {zf.namelist()}")
        # Take the largest text file (main data)
        name = max(txt_files, key=lambda n: zf.getinfo(n).file_size)
        return zf.read(name).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_cot_readings() -> list[CotWeeklyReading]:
    """Fetch and parse COT data. Returns [] on any failure (graceful degradation).

    Returns all weekly readings in the YTD file.  Latest week per market has
    the highest report_date.  Consumers should filter/group as needed.
    """
    try:
        zip_bytes = _get_zip_bytes()
    except Exception as e:
        logger.warning("COT download failed: %s", e)
        return []

    try:
        csv_text = _extract_csv(zip_bytes)
    except Exception as e:
        logger.warning("COT ZIP extract failed: %s", e)
        return []

    try:
        rows = _parse_rows(csv_text)
    except Exception as e:
        logger.warning("COT parse failed: %s", e)
        return []

    logger.info("COT: parsed %d readings across %d markets", len(rows), len({r.market for r in rows}))
    return rows
