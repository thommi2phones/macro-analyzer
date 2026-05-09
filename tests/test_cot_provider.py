"""Tests for cot_provider: parsing, market matching, graceful degradation."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

from macro_positioning.market.cot_provider import (
    CotWeeklyReading,
    _match_market,
    _parse_report_date,
    _parse_rows,
    _extract_csv,
)


# ---------------------------------------------------------------------------
# _match_market
# ---------------------------------------------------------------------------

class TestMatchMarket:
    # Market names verified against fut_disagg_txt_2026.zip (disaggregated format)
    def test_crude_oil_wti_financial(self):
        assert _match_market("WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE") == "Crude Oil (WTI)"

    def test_crude_oil_light_sweet(self):
        assert _match_market("CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE") == "Crude Oil (WTI)"

    def test_gold_disaggregated(self):
        assert _match_market("GOLD - COMMODITY EXCHANGE INC.") == "Gold"

    def test_natural_gas_nyme(self):
        assert _match_market("NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE") == "Natural Gas"

    def test_natural_gas_henry_hub(self):
        assert _match_market("NATURAL GAS (HENRY HUB) - NEW YORK MERCANTILE EXCHANGE") == "Natural Gas"

    def test_corn(self):
        assert _match_market("CORN - CHICAGO BOARD OF TRADE") == "Corn"

    def test_soybeans(self):
        assert _match_market("SOYBEANS - CHICAGO BOARD OF TRADE") == "Soybeans"

    def test_wheat_srw(self):
        assert _match_market("WHEAT-SRW - CHICAGO BOARD OF TRADE") == "Wheat"

    def test_bitcoin(self):
        assert _match_market("BITCOIN - CHICAGO MERCANTILE EXCHANGE") == "Bitcoin"

    def test_sp500(self):
        assert _match_market("S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE") == "S&P 500"

    def test_euro_fx(self):
        assert _match_market("EURO FX - CHICAGO MERCANTILE EXCHANGE") == "EUR/USD"

    def test_10y_treasury(self):
        assert _match_market("10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE") == "10Y Treasury"

    def test_2y_treasury(self):
        assert _match_market("2-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE") == "2Y Treasury"

    def test_no_match_returns_none(self):
        assert _match_market("LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE") is None

    def test_case_insensitive(self):
        assert _match_market("gold - commodity exchange inc.") == "Gold"


# ---------------------------------------------------------------------------
# _parse_report_date
# ---------------------------------------------------------------------------

class TestParseReportDate:
    def test_yymmdd_disagg_format(self):
        # disaggregated uses capital 'In'
        assert _parse_report_date({"As_of_Date_In_Form_YYMMDD": "250103"}) == date(2025, 1, 3)

    def test_yymmdd_legacy_format(self):
        assert _parse_report_date({"As_of_Date_in_Form_YYMMDD": "250103"}) == date(2025, 1, 3)

    def test_iso_date_format(self):
        assert _parse_report_date({"Report_Date_as_YYYY-MM-DD": "2025-01-03"}) == date(2025, 1, 3)

    def test_mm_dd_yyyy_format(self):
        assert _parse_report_date({"Report_Date_as_MM_DD_YYYY": "01/03/2025"}) == date(2025, 1, 3)

    def test_empty_returns_none(self):
        assert _parse_report_date({}) is None

    def test_invalid_returns_none(self):
        assert _parse_report_date({"As_of_Date_in_Form_YYMMDD": "not-a-date"}) is None


# ---------------------------------------------------------------------------
# _parse_rows  (end-to-end parsing from synthetic CSV)
# ---------------------------------------------------------------------------

def _make_csv(*rows: dict) -> str:
    """Build a minimal COT CSV string from dicts."""
    if not rows:
        return ""
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


_GOLD_ROW = {
    "Market_and_Exchange_Names": "GOLD - COMMODITY EXCHANGE INC.",
    "As_of_Date_In_Form_YYMMDD": "250103",    # disaggregated column (capital 'In')
    "Report_Date_as_YYYY-MM-DD": "2025-01-03",
    "Open_Interest_All": "500000",
    "M_Money_Positions_Long_All": "180000",    # managed money = speculative proxy
    "M_Money_Positions_Short_All": "80000",
    "Noncommercial_Positions_Long_All": "",    # not present in disaggregated
    "Noncommercial_Positions_Short_All": "",
}


class TestParseRows:
    def test_basic_gold_row(self):
        csv_text = _make_csv(_GOLD_ROW)
        results = _parse_rows(csv_text)
        assert len(results) == 1
        r = results[0]
        assert r.market == "Gold"
        assert r.noncomm_long == 180000
        assert r.noncomm_short == 80000
        assert r.noncomm_net == 100000
        assert r.open_interest == 500000
        assert abs(r.net_pct_oi - 20.0) < 0.01

    def test_unknown_market_skipped(self):
        row = dict(_GOLD_ROW)
        row["Market_and_Exchange_Names"] = "LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE"
        assert _parse_rows(_make_csv(row)) == []

    def test_zero_oi_skipped(self):
        row = dict(_GOLD_ROW, **{"Open_Interest_All": "0"})
        assert _parse_rows(_make_csv(row)) == []

    def test_net_negative_when_short_dominant(self):
        row = dict(_GOLD_ROW, **{
            "M_Money_Positions_Long_All": "60000",
            "M_Money_Positions_Short_All": "140000",
        })
        results = _parse_rows(_make_csv(row))
        assert results[0].noncomm_net == -80000
        assert results[0].net_pct_oi < 0

    def test_comma_separated_numbers_parsed(self):
        row = dict(_GOLD_ROW, **{
            "Open_Interest_All": "500,000",
            "M_Money_Positions_Long_All": "180,000",
            "M_Money_Positions_Short_All": "80,000",
        })
        results = _parse_rows(_make_csv(row))
        assert results[0].open_interest == 500000

    def test_multiple_markets(self):
        crude_row = {
            "Market_and_Exchange_Names": "WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
            "As_of_Date_In_Form_YYMMDD": "250103",
            "Report_Date_as_YYYY-MM-DD": "2025-01-03",
            "Open_Interest_All": "1000000",
            "M_Money_Positions_Long_All": "300000",
            "M_Money_Positions_Short_All": "200000",
            "Noncommercial_Positions_Long_All": "",
            "Noncommercial_Positions_Short_All": "",
        }
        results = _parse_rows(_make_csv(_GOLD_ROW, crude_row))
        markets = {r.market for r in results}
        assert "Gold" in markets
        assert "Crude Oil (WTI)" in markets

    def test_empty_csv_returns_empty(self):
        assert _parse_rows("") == []


# ---------------------------------------------------------------------------
# _extract_csv
# ---------------------------------------------------------------------------

class TestExtractCsv:
    def _make_zip(self, files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content.encode())
        return buf.getvalue()

    def test_extracts_txt_file(self):
        content = "header\nrow1\n"
        zip_bytes = self._make_zip({"annualof.txt": content})
        assert _extract_csv(zip_bytes) == content

    def test_picks_largest_txt(self):
        zip_bytes = self._make_zip({
            "small.txt": "a",
            "large.txt": "b" * 1000,
        })
        result = _extract_csv(zip_bytes)
        assert result == "b" * 1000

    def test_no_txt_raises(self):
        zip_bytes = self._make_zip({"readme.pdf": "data"})
        try:
            _extract_csv(zip_bytes)
            assert False, "should have raised"
        except ValueError:
            pass
