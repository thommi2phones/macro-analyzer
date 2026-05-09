from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        published_at TEXT NOT NULL,
        author TEXT,
        content_type TEXT NOT NULL,
        raw_text TEXT NOT NULL,
        cleaned_text TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        ingested_at TEXT NOT NULL
    )
    """,
    # Dedup: two documents from the same source with the same URL are the
    # same story. NULL urls don't collide under SQLite's unique semantics,
    # so untitled/url-less sources still dedupe via their document_id PK.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_url
        ON documents (source_id, url)
        WHERE url IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS theses (
        thesis_id TEXT PRIMARY KEY,
        thesis TEXT NOT NULL,
        theme TEXT NOT NULL,
        horizon TEXT NOT NULL,
        direction TEXT NOT NULL,
        assets_json TEXT NOT NULL,
        catalysts_json TEXT NOT NULL,
        risks_json TEXT NOT NULL,
        implied_positioning_json TEXT NOT NULL,
        confidence REAL NOT NULL,
        freshness_score REAL NOT NULL,
        status TEXT NOT NULL,
        source_ids_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        extracted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memos (
        memo_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        summary TEXT NOT NULL,
        consensus_views_json TEXT NOT NULL,
        divergent_views_json TEXT NOT NULL,
        suggested_positioning_json TEXT NOT NULL,
        risks_to_watch_json TEXT NOT NULL,
        thesis_ids_json TEXT NOT NULL
    )
    """,
    # ─── Trading framework §13 schema ──────────────────────────────────────
    # See docs/trading_framework.md and config/trading_framework.json.
    # These tables back the brain's scoring engine + manual trade journal.
    """
    CREATE TABLE IF NOT EXISTS assets (
        asset_id TEXT PRIMARY KEY,
        ticker TEXT NOT NULL,
        asset_name TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        sector TEXT,
        theme TEXT,
        liquidity_profile TEXT,
        volatility_profile TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_ticker ON assets (ticker)
    """,
    """
    CREATE TABLE IF NOT EXISTS macro_regimes (
        regime_id TEXT PRIMARY KEY,
        classified_at TEXT NOT NULL,
        framework_regime TEXT NOT NULL,
        thesis_regime TEXT NOT NULL,
        liquidity_state TEXT,
        dollar_trend TEXT,
        rate_trend TEXT,
        volatility_state TEXT,
        breadth_state TEXT,
        confidence_score INTEGER NOT NULL,
        classifier_version TEXT,
        evidence_json TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_macro_regimes_classified_at
        ON macro_regimes (classified_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_setups (
        setup_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        setup_type TEXT NOT NULL,
        market_structure TEXT NOT NULL,
        key_level REAL,
        entry_zone_low REAL,
        entry_zone_high REAL,
        invalidation_level REAL,
        target_zone_low REAL,
        target_zone_high REAL,
        risk_reward REAL,
        technical_score INTEGER NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets (asset_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_setups_asset
        ON technical_setups (asset_id, observed_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS volume_signals (
        volume_signal_id TEXT PRIMARY KEY,
        setup_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        relative_volume REAL,
        volume_pattern TEXT,
        volume_confirmation TEXT,
        volume_score INTEGER NOT NULL,
        FOREIGN KEY (setup_id) REFERENCES technical_setups (setup_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_scores (
        score_id TEXT PRIMARY KEY,
        setup_id TEXT NOT NULL,
        scored_at TEXT NOT NULL,
        regime_id TEXT,
        macro_alignment_score INTEGER NOT NULL,
        liquidity_score INTEGER NOT NULL,
        sector_theme_score INTEGER NOT NULL,
        technical_structure_score INTEGER NOT NULL,
        volume_flow_score INTEGER NOT NULL,
        risk_reward_score INTEGER NOT NULL,
        relative_strength_score INTEGER NOT NULL,
        psychology_score INTEGER NOT NULL,
        raw_total_score INTEGER NOT NULL,
        adjusted_total_score INTEGER NOT NULL,
        grade TEXT NOT NULL,
        position_size_tier TEXT NOT NULL,
        feature_vector_json TEXT,
        reasoning_trail_json TEXT,
        FOREIGN KEY (setup_id) REFERENCES technical_setups (setup_id),
        FOREIGN KEY (regime_id) REFERENCES macro_regimes (regime_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_trade_scores_setup
        ON trade_scores (setup_id, scored_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        setup_id TEXT,
        score_id TEXT,
        asset_id TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_date TEXT,
        exit_price REAL,
        position_size REAL NOT NULL,
        stop_loss REAL NOT NULL,
        target_price REAL,
        status TEXT NOT NULL,
        pnl REAL,
        pnl_percent REAL,
        execution_notes TEXT,
        was_it_thesis_at_close TEXT,
        lesson_at_close TEXT,
        hindsight_bias_check TEXT,
        FOREIGN KEY (setup_id) REFERENCES technical_setups (setup_id),
        FOREIGN KEY (score_id) REFERENCES trade_scores (score_id),
        FOREIGN KEY (asset_id) REFERENCES assets (asset_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_trades_status_entry
        ON trades (status, entry_date DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS missed_trades (
        missed_trade_id TEXT PRIMARY KEY,
        setup_id TEXT NOT NULL,
        flagged_at TEXT NOT NULL,
        reason_missed TEXT NOT NULL,
        was_valid_in_real_time INTEGER NOT NULL,
        hindsight_bias_risk TEXT NOT NULL,
        lesson TEXT,
        rule_adjustment TEXT,
        FOREIGN KEY (setup_id) REFERENCES technical_setups (setup_id)
    )
    """,
    # ─── Inputs workstream: per-source per-trade attribution ──────────────
    """
    CREATE TABLE IF NOT EXISTS source_outcomes (
        outcome_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        trade_id TEXT NOT NULL,
        thesis_id TEXT,
        attribution_weight REAL NOT NULL,
        outcome_pnl REAL,
        outcome_pnl_percent REAL,
        contribution_type TEXT,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (trade_id) REFERENCES trades (trade_id),
        FOREIGN KEY (thesis_id) REFERENCES theses (thesis_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_source_outcomes_source
        ON source_outcomes (source_id, recorded_at DESC)
    """,
    # ─── Logging contract: every agent call logged for future fine-tune ───
    # See docs/logging_contract.md. This is the training corpus seed table.
    """
    CREATE TABLE IF NOT EXISTS agent_call_log (
        call_id TEXT PRIMARY KEY,
        agent_name TEXT NOT NULL,
        called_at TEXT NOT NULL,
        model_provider TEXT NOT NULL,
        model_name TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        input_payload_json TEXT NOT NULL,
        output_payload_json TEXT NOT NULL,
        context_json TEXT,
        latency_ms INTEGER,
        input_tokens INTEGER,
        output_tokens INTEGER,
        estimated_cost_usd REAL,
        success INTEGER NOT NULL,
        error_message TEXT,
        attributed_setup_id TEXT,
        attributed_trade_id TEXT,
        attributed_outcome_pnl REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_call_log_agent_called
        ON agent_call_log (agent_name, called_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_call_log_attribution
        ON agent_call_log (attributed_trade_id)
        WHERE attributed_trade_id IS NOT NULL
    """,
    # ─── Decisions log: chat-driven architecture/scope decisions ──────────
    # Backs the mgmt panel; also future training pairs.
    """
    CREATE TABLE IF NOT EXISTS decisions (
        decision_id TEXT PRIMARY KEY,
        decided_at TEXT NOT NULL,
        topic TEXT NOT NULL,
        decision TEXT NOT NULL,
        rationale TEXT,
        alternatives_considered TEXT,
        chat_session_ref TEXT,
        affects_files TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_decisions_decided_at
        ON decisions (decided_at DESC)
    """,
    # ─── Live prices: daily OHLCV per ticker ──────────────────────────────
    # Populated by the prices/fetcher.py batch + the `prices fetch` CLI.
    # Keyed on ticker (string) rather than asset_id (FK) so we can fetch
    # before assets row exists; the scoring runner writes assets first
    # then trade_scores so this stays consistent.
    """
    CREATE TABLE IF NOT EXISTS prices (
        price_id TEXT PRIMARY KEY,
        ticker TEXT NOT NULL,
        observed_at TEXT NOT NULL,        -- ISO date (YYYY-MM-DD) for daily; ISO datetime for intraday
        timeframe TEXT NOT NULL DEFAULT '1D',
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL,
        volume INTEGER,
        provider TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
    """,
    # One bar per (ticker, observed_at, timeframe) — re-fetches replace via INSERT OR REPLACE
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_ticker_observed
        ON prices (ticker, observed_at, timeframe)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_prices_ticker_observed_desc
        ON prices (ticker, observed_at DESC)
    """,
]


def _dedupe_existing_documents(connection: sqlite3.Connection) -> int:
    """Remove duplicate (source_id, url) rows keeping the earliest ingested_at.

    Called before creating the unique index so upgrades on databases that
    accumulated duplicates under the old INSERT OR REPLACE path don't fail.
    """
    # Only runs if the documents table already exists.
    table_exists = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    if not table_exists:
        return 0

    cursor = connection.execute(
        """
        DELETE FROM documents
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM documents
            WHERE url IS NOT NULL
            GROUP BY source_id, url
        )
        AND url IS NOT NULL
        """
    )
    return cursor.rowcount or 0


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        # WAL mode = concurrent reads + single writer without lock contention.
        # Critical when the FastAPI server is reading desk_data while a CLI
        # score-pass writes to trade_scores. Default rollback-journal mode
        # would lock the whole DB on writes and stall both sides.
        # Persists in the file's pragma so we only need to set it once.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        # Wait up to 5s for any in-flight writer rather than failing fast
        # with `database is locked`. Safe with WAL because contention
        # windows are short.
        connection.execute("PRAGMA busy_timeout=5000")
        # Create base tables first (documents must exist before dedupe).
        connection.execute(SCHEMA_STATEMENTS[0])
        # Dedupe any pre-existing duplicates before the unique index lands.
        _dedupe_existing_documents(connection)
        for statement in SCHEMA_STATEMENTS[1:]:
            connection.execute(statement)
        connection.commit()
