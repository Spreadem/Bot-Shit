"""Runtime configuration for funding arbitrage bot."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class RiskConfig(BaseModel):
    max_total_notional_usd: float = 8_000
    max_notional_per_symbol_usd: float = 2_000
    max_open_positions: int = 3
    max_daily_loss_usd: float = 150
    max_drawdown_usd: float = 300
    max_consecutive_errors: int = 10
    max_api_latency_ms: int = 2_500
    max_ws_lag_ms: int = 5_000
    min_liq_buffer_pct: float = 12
    max_notional_drift_pct: float = 0.3


class StrategyConfig(BaseModel):
    top_n_coins: int = 10
    leverage: int = 2
    min_funding_diff_bps: float = 3
    exit_diff_bps: float = 1
    max_entry_spread_bps: float = 8
    taker_fee_bps: float = 6
    maker_fee_bps: float = 2
    slippage_buffer_bps: float = 2
    capital_usd: float = 10_000
    allocation_per_symbol: float = 0.1
    entry_mode: Literal["maker_hybrid", "ioc", "market"] = "maker_hybrid"
    maker_timeout_ms: int = 1500
    top_of_book_offset_ticks: int = 1
    sequential_entry: bool = True
    max_leg_gap_ms: int = 1500

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, value: int) -> int:
        if value < 2 or value > 10:
            raise ValueError("LEVERAGE must be in [2, 10]")
        return value


class BotConfig(BaseSettings):
    """Configuration loaded from env and optional config file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bybit_api_key: str = Field(default="", alias="BYBIT_API_KEY")
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    kucoin_api_key: str = Field(default="", alias="KUCOIN_API_KEY")
    kucoin_api_secret: str = Field(default="", alias="KUCOIN_API_SECRET")
    kucoin_api_passphrase: str = Field(default="", alias="KUCOIN_API_PASSPHRASE")

    db_path: str = "bot_state.sqlite3"
    live_tiny_notional_usd: float = 100
    poll_interval_sec: float = 3.0
    hard_kill_switch: bool = False

    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)

    default_symbols: list[str] = Field(
        default_factory=lambda: [
            "BTC",
            "ETH",
            "SOL",
            "XRP",
            "DOGE",
            "ADA",
            "AVAX",
            "LINK",
            "DOT",
            "LTC",
        ]
    )

    @classmethod
    def from_file(cls, path: str | None = None) -> "BotConfig":
        if not path:
            return cls()
        raw = Path(path).read_text(encoding="utf-8")
        import json

        data = json.loads(raw)
        return cls(**data)
