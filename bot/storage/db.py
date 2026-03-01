"""SQLite storage for observations, trades, and risk snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from bot.models import FundingSnapshot, Position


class DB:
    def __init__(self, path: str):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self._init()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS funding_observations (
                ts TEXT,
                symbol TEXT,
                exchange TEXT,
                funding_rate REAL,
                next_funding_time TEXT,
                mark_price REAL,
                index_price REAL,
                bid REAL,
                ask REAL
            );
            CREATE TABLE IF NOT EXISTS trades (
                ts TEXT,
                symbol TEXT,
                exchange TEXT,
                side TEXT,
                qty REAL,
                price REAL,
                action TEXT
            );
            CREATE TABLE IF NOT EXISTS pnl (
                ts TEXT,
                realized REAL,
                unrealized REAL,
                fees REAL,
                funding_captured REAL
            );
            CREATE TABLE IF NOT EXISTS liq_buffer (
                ts TEXT,
                symbol TEXT,
                exchange TEXT,
                liq_buffer_pct REAL
            );
            """
        )
        self.conn.commit()

    def save_funding(self, snap: FundingSnapshot) -> None:
        self.conn.execute(
            "INSERT INTO funding_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                snap.symbol,
                snap.exchange.value,
                snap.funding_rate,
                snap.next_funding_time.isoformat() if snap.next_funding_time else None,
                snap.mark_price,
                snap.index_price,
                snap.bid,
                snap.ask,
            ),
        )
        self.conn.commit()

    def save_trade(self, symbol: str, exchange: str, side: str, qty: float, price: float, action: str) -> None:
        self.conn.execute(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), symbol, exchange, side, qty, price, action),
        )
        self.conn.commit()

    def save_pnl(self, realized: float, unrealized: float, fees: float, funding_captured: float) -> None:
        self.conn.execute(
            "INSERT INTO pnl VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), realized, unrealized, fees, funding_captured),
        )
        self.conn.commit()

    def save_liq_buffer(self, position: Position, liq_buffer_pct: float) -> None:
        self.conn.execute(
            "INSERT INTO liq_buffer VALUES (?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), position.symbol, position.exchange.value, liq_buffer_pct),
        )
        self.conn.commit()

    def daily_metrics(self) -> dict[str, float]:
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(SUM(realized),0), COALESCE(SUM(fees),0), COALESCE(SUM(funding_captured),0) FROM pnl")
        r = cur.fetchone() or (0.0, 0.0, 0.0)
        return {
            "daily_pnl": float(r[0]),
            "fees": float(r[1]),
            "funding_captured": float(r[2]),
        }

    def close(self) -> None:
        self.conn.close()
