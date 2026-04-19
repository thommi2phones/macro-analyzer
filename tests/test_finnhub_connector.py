"""Tests for the Finnhub connector (mocked via httpx.MockTransport)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from macro_positioning.ingestion import finnhub_connector as fh

_RealClient = httpx.Client


def _install_mock(monkeypatch, routes: dict):
    """Install a fake httpx.Client inside the connector module.

    routes: {path: json_response} keyed by request.url.path.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"error": f"no route for {path}"})

    transport = httpx.MockTransport(handler)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self._client = _RealClient(transport=transport)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._client.close()

        def get(self, url, params=None, **kwargs):
            return self._client.get(url, params=params, **kwargs)

    monkeypatch.setattr(fh.httpx, "Client", _FakeClient)


class TestFetchCompanyNews:
    def test_maps_items_to_raw_documents(self, monkeypatch):
        payload = [
            {
                "headline": "AAPL surges on earnings",
                "summary": "Apple beat expectations for Q3.",
                "url": "https://example.com/aapl-1",
                "datetime": 1700000000,
                "source": "Reuters",
            },
            {
                "headline": "",  # should be skipped
                "summary": "no headline",
                "datetime": 1700000001,
            },
            {
                "headline": "Supply chain risk",
                "summary": "",
                "url": "https://example.com/aapl-2",
                "datetime": 1700000002,
                "source": "Bloomberg",
            },
        ]
        _install_mock(monkeypatch, {"/api/v1/company-news": payload})

        docs = fh.fetch_company_news("AAPL", days=7, api_key="test-key")

        assert len(docs) == 2
        assert docs[0].source_id == "finnhub_aapl"
        assert docs[0].title == "AAPL surges on earnings"
        assert docs[0].url == "https://example.com/aapl-1"
        assert docs[0].author == "Reuters"
        assert "finnhub" in docs[0].tags
        assert "aapl" in docs[0].tags
        # datetime must be tz-aware UTC
        assert docs[0].published_at.tzinfo is not None
        # Falls back to title when summary empty
        assert docs[1].raw_text == "Supply chain risk"

    def test_empty_list_on_api_error(self, monkeypatch):
        def handler(request):
            return httpx.Response(500, json={"error": "server"})
        transport = httpx.MockTransport(handler)

        class _FakeClient:
            def __init__(self, *a, **kw):
                self._c = _RealClient(transport=transport)
            def __enter__(self): return self
            def __exit__(self, *e): self._c.close()
            def get(self, url, params=None, **kw):
                return self._c.get(url, params=params, **kw)

        monkeypatch.setattr(fh.httpx, "Client", _FakeClient)
        assert fh.fetch_company_news("AAPL", api_key="k") == []

    def test_missing_api_key_resolve_raises(self, monkeypatch):
        monkeypatch.setattr(fh.settings, "finnhub_api_key", "")
        with pytest.raises(RuntimeError, match="Finnhub API key"):
            fh._resolve_key(None)

    def test_missing_api_key_public_returns_empty(self, monkeypatch):
        monkeypatch.setattr(fh.settings, "finnhub_api_key", "")
        assert fh.fetch_company_news("AAPL") == []


class TestFetchGeneralNews:
    def test_general_category(self, monkeypatch):
        payload = [
            {
                "headline": "Markets rally broadly",
                "summary": "Global equities up",
                "url": "https://example.com/mkt",
                "datetime": 1700000500,
                "source": "FT",
            }
        ]
        _install_mock(monkeypatch, {"/api/v1/news": payload})
        docs = fh.fetch_general_news("general", api_key="k")
        assert len(docs) == 1
        assert docs[0].source_id == "finnhub_general"
        assert "general" in docs[0].tags

    def test_unexpected_shape_returns_empty(self, monkeypatch):
        _install_mock(monkeypatch, {"/api/v1/news": {"not": "a list"}})
        assert fh.fetch_general_news("forex", api_key="k") == []


class TestFetchNewsSentiment:
    def test_sentiment_payload(self, monkeypatch):
        payload = {
            "symbol": "TSLA",
            "buzz": {
                "articlesInLastWeek": 42,
                "buzz": 1.2,
                "weeklyAverage": 35.0,
            },
            "sentiment": {
                "bearishPercent": 0.3,
                "bullishPercent": 0.7,
            },
            "companyNewsScore": 0.85,
            "sectorAverageBullishPercent": 0.55,
            "sectorAverageNewsScore": 0.6,
        }
        _install_mock(monkeypatch, {"/api/v1/news-sentiment": payload})
        result = fh.fetch_news_sentiment("TSLA", api_key="k")
        assert result["symbol"] == "TSLA"
        assert result["buzz"]["articles_in_last_week"] == 42
        assert result["sentiment"]["bullish_percent"] == 0.7
        assert result["company_news_score"] == 0.85

    def test_sentiment_error_returns_dict(self, monkeypatch):
        def handler(request):
            return httpx.Response(500, json={"error": "boom"})
        transport = httpx.MockTransport(handler)

        class _FakeClient:
            def __init__(self, *a, **kw):
                self._c = _RealClient(transport=transport)
            def __enter__(self): return self
            def __exit__(self, *e): self._c.close()
            def get(self, url, params=None, **kw):
                return self._c.get(url, params=params, **kw)

        monkeypatch.setattr(fh.httpx, "Client", _FakeClient)
        result = fh.fetch_news_sentiment("TSLA", api_key="k")
        assert "error" in result
