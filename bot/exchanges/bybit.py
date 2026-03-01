"""Bybit USDT perp adapter (v5)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any, Sequence

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.models import ExchangeName, FundingSnapshot, HealthStatus, OrderRequest, OrderResult, Position, Side, SymbolInfo
from .base import PerpExchange


class BybitExchange(PerpExchange):
    name = ExchangeName.BYBIT.value

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.client = httpx.AsyncClient(timeout=10)

    async def close(self) -> None:
        await self.client.aclose()

    def _sign(self, params: dict[str, Any]) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        recv = "5000"
        body = json.dumps(params, separators=(",", ":")) if params else ""
        payload = f"{ts}{self.api_key}{recv}{body}"
        sig = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sig,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv,
            "Content-Type": "application/json",
        }

    async def _public_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        r = await self.client.get(f"{self.base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    async def _private_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._sign(payload)
        r = await self.client.post(f"{self.base}{path}", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def _private_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = self._sign(params)
        r = await self.client.get(f"{self.base}{path}", headers=headers, params=params)
        r.raise_for_status()
        return r.json()

    async def ping(self) -> HealthStatus:
        start = time.perf_counter()
        err = None
        ok = True
        try:
            await self._public_get("/v5/market/time", {})
        except Exception as exc:  # pragma: no cover - network branch
            ok = False
            err = str(exc)
        latency = (time.perf_counter() - start) * 1000
        return HealthStatus(exchange=ExchangeName.BYBIT, api_ok=ok, latency_ms=latency, last_error=err)

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=5), stop=stop_after_attempt(3))
    async def get_top_usdt_perps(self, top_n: int) -> list[SymbolInfo]:
        data = await self._public_get("/v5/market/tickers", {"category": "linear"})
        rows = data.get("result", {}).get("list", [])
        ranked = sorted(rows, key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
        out: list[SymbolInfo] = []
        for row in ranked:
            symbol = row.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            info = await self._public_get(
                "/v5/market/instruments-info", {"category": "linear", "symbol": symbol}
            )
            lst = info.get("result", {}).get("list", [])
            if not lst:
                continue
            spec = lst[0]
            lot = spec.get("lotSizeFilter", {})
            price_filter = spec.get("priceFilter", {})
            out.append(
                SymbolInfo(
                    symbol=symbol,
                    exchange=ExchangeName.BYBIT,
                    min_qty=float(lot.get("minOrderQty", 0.001)),
                    qty_step=float(lot.get("qtyStep", 0.001)),
                    tick_size=float(price_filter.get("tickSize", 0.1)),
                    turnover_24h=float(row.get("turnover24h", 0.0)),
                )
            )
            if len(out) >= top_n:
                break
        return out

    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot:
        ticker = await self._public_get(
            "/v5/market/tickers", {"category": "linear", "symbol": symbol}
        )
        row = ticker.get("result", {}).get("list", [{}])[0]
        funding_rate = float(row.get("fundingRate", 0.0))
        next_funding = row.get("nextFundingTime")
        orderbook = await self._public_get(
            "/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": 1}
        )
        ob = orderbook.get("result", {})
        bid = float(ob.get("b", [[0, 0]])[0][0])
        ask = float(ob.get("a", [[0, 0]])[0][0])
        next_funding_dt = (
            datetime.fromtimestamp(int(next_funding) / 1000, tz=UTC).replace(tzinfo=None)
            if next_funding
            else None
        )
        return FundingSnapshot(
            symbol=symbol,
            exchange=ExchangeName.BYBIT,
            funding_rate=funding_rate,
            next_funding_time=next_funding_dt,
            mark_price=float(row.get("markPrice", 0.0)),
            index_price=float(row.get("indexPrice", 0.0)),
            bid=bid,
            ask=ask,
        )

    async def get_positions(self) -> list[Position]:
        if not self.api_key:
            return []
        data = await self._private_get("/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
        rows = data.get("result", {}).get("list", [])
        out: list[Position] = []
        for row in rows:
            size = float(row.get("size", 0.0))
            if size == 0:
                continue
            side = Side.BUY if row.get("side", "").lower() == "buy" else Side.SELL
            out.append(
                Position(
                    symbol=row.get("symbol", ""),
                    exchange=ExchangeName.BYBIT,
                    side=side,
                    qty=size,
                    entry_price=float(row.get("avgPrice", 0.0)),
                    mark_price=float(row.get("markPrice", 0.0)),
                    liquidation_price=float(row.get("liqPrice", 0.0) or 0.0),
                    maintenance_margin=float(row.get("positionMM", 0.0) or 0.0),
                    isolated=row.get("tradeMode", 0) == 1,
                )
            )
        return out

    async def place_order(self, order: OrderRequest) -> OrderResult:
        payload = {
            "category": "linear",
            "symbol": order.symbol,
            "side": "Buy" if order.side == Side.BUY else "Sell",
            "orderType": "Market" if order.mode == "market" else "Limit",
            "qty": str(order.qty),
            "timeInForce": "PostOnly" if order.post_only else ("IOC" if order.mode == "ioc" else "GTC"),
            "reduceOnly": order.reduce_only,
        }
        if order.price is not None:
            payload["price"] = str(order.price)
        try:
            data = await self._private_post("/v5/order/create", payload)
            oid = data.get("result", {}).get("orderId")
            return OrderResult(True, oid, 0.0, order.price)
        except Exception as exc:  # pragma: no cover
            return OrderResult(False, None, 0.0, None, str(exc))

    async def cancel_all_orders(self, symbols: Sequence[str] | None = None) -> None:
        symbols = symbols or []
        for sym in symbols:
            await self._private_post("/v5/order/cancel-all", {"category": "linear", "symbol": sym})

    async def set_leverage_isolated(self, symbol: str, leverage: int) -> None:
        # TODO: Some accounts require switching mode endpoint first.
        await self._private_post(
            "/v5/position/set-leverage",
            {"category": "linear", "symbol": symbol, "buyLeverage": str(leverage), "sellLeverage": str(leverage)},
        )
        await self._private_post(
            "/v5/position/switch-isolated",
            {"category": "linear", "symbol": symbol, "tradeMode": 1, "buyLeverage": str(leverage), "sellLeverage": str(leverage)},
        )
