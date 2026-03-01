"""KuCoin Futures USDT perp adapter."""

from __future__ import annotations

import base64
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


class KucoinExchange(PerpExchange):
    name = ExchangeName.KUCOIN.value

    def __init__(self, api_key: str, api_secret: str, api_passphrase: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.base = "https://api-sandbox-futures.kucoin.com" if testnet else "https://api-futures.kucoin.com"
        self.client = httpx.AsyncClient(timeout=10)

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, method: str, endpoint: str, body: dict[str, Any] | None = None) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        body_s = json.dumps(body) if body else ""
        prehash = f"{ts}{method.upper()}{endpoint}{body_s}"
        sign = base64.b64encode(hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        pphrase = base64.b64encode(
            hmac.new(self.api_secret.encode(), self.api_passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": ts,
            "KC-API-PASSPHRASE": pphrase,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json",
        }

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = await self.client.get(f"{self.base}{endpoint}", params=params)
        r.raise_for_status()
        return r.json()

    async def _private_get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = self._headers("GET", endpoint)
        r = await self.client.get(f"{self.base}{endpoint}", params=params, headers=headers)
        r.raise_for_status()
        return r.json()

    async def _private_post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers("POST", endpoint, payload)
        r = await self.client.post(f"{self.base}{endpoint}", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def ping(self) -> HealthStatus:
        start = time.perf_counter()
        ok, err = True, None
        try:
            await self._get("/api/v1/timestamp")
        except Exception as exc:  # pragma: no cover
            ok, err = False, str(exc)
        return HealthStatus(exchange=ExchangeName.KUCOIN, api_ok=ok, latency_ms=(time.perf_counter() - start) * 1000, last_error=err)

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=5), stop=stop_after_attempt(3))
    async def get_top_usdt_perps(self, top_n: int) -> list[SymbolInfo]:
        data = await self._get("/api/v1/contracts/active")
        rows = data.get("data", [])
        usdt = [r for r in rows if r.get("quoteCurrency") == "USDT" and r.get("status") == "Open"]
        ranked = sorted(usdt, key=lambda x: float(x.get("turnoverOf24h", 0)), reverse=True)
        out: list[SymbolInfo] = []
        for row in ranked[:top_n]:
            out.append(
                SymbolInfo(
                    symbol=row["symbol"],
                    exchange=ExchangeName.KUCOIN,
                    min_qty=float(row.get("lotSize", 1)),
                    qty_step=float(row.get("lotSize", 1)),
                    tick_size=float(row.get("tickSize", 0.1)),
                    turnover_24h=float(row.get("turnoverOf24h", 0.0)),
                )
            )
        return out

    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot:
        ticker = await self._get("/api/v1/ticker", {"symbol": symbol})
        tr = ticker.get("data", {})
        funding = await self._get("/api/v1/funding-rate/" + symbol)
        fr = funding.get("data", {})
        ob = await self._get("/api/v1/level2/snapshot", {"symbol": symbol})
        obd = ob.get("data", {})
        bid = float(obd.get("bids", [[0, 0]])[0][0])
        ask = float(obd.get("asks", [[0, 0]])[0][0])
        next_funding = fr.get("nextFundingRateTime")
        next_funding_dt = (
            datetime.fromtimestamp(int(next_funding) / 1000, tz=UTC).replace(tzinfo=None)
            if next_funding
            else None
        )
        return FundingSnapshot(
            symbol=symbol,
            exchange=ExchangeName.KUCOIN,
            funding_rate=float(fr.get("value", 0.0)),
            next_funding_time=next_funding_dt,
            mark_price=float(tr.get("markPrice", 0.0)),
            index_price=float(tr.get("indexPrice", 0.0)),
            bid=bid,
            ask=ask,
        )

    async def get_positions(self) -> list[Position]:
        if not self.api_key:
            return []
        data = await self._private_get("/api/v1/positions")
        rows = data.get("data", [])
        out: list[Position] = []
        for row in rows:
            qty = abs(float(row.get("currentQty", 0.0)))
            if qty == 0:
                continue
            side = Side.BUY if float(row.get("currentQty", 0.0)) > 0 else Side.SELL
            out.append(
                Position(
                    symbol=row.get("symbol", ""),
                    exchange=ExchangeName.KUCOIN,
                    side=side,
                    qty=qty,
                    entry_price=float(row.get("avgEntryPrice", 0.0)),
                    mark_price=float(row.get("markPrice", 0.0)),
                    liquidation_price=float(row.get("liquidationPrice", 0.0) or 0.0),
                    maintenance_margin=float(row.get("maintMarginReq", 0.0) or 0.0),
                    isolated=row.get("marginMode", "ISOLATED") == "ISOLATED",
                )
            )
        return out

    async def place_order(self, order: OrderRequest) -> OrderResult:
        payload = {
            "clientOid": f"arb-{int(time.time()*1000)}",
            "symbol": order.symbol,
            "side": "buy" if order.side == Side.BUY else "sell",
            "type": "market" if order.mode == "market" else "limit",
            "size": str(order.qty),
            "postOnly": order.post_only,
            "reduceOnly": order.reduce_only,
        }
        if order.mode == "ioc":
            payload["timeInForce"] = "IOC"
        if order.price is not None:
            payload["price"] = str(order.price)
        try:
            data = await self._private_post("/api/v1/orders", payload)
            oid = data.get("data", {}).get("orderId")
            return OrderResult(True, oid, 0.0, order.price)
        except Exception as exc:  # pragma: no cover
            return OrderResult(False, None, 0.0, None, str(exc))

    async def cancel_all_orders(self, symbols: Sequence[str] | None = None) -> None:
        await self._private_delete_all()

    async def _private_delete_all(self) -> None:
        # TODO: if you need per-symbol cancellation use /api/v1/orders?symbol=...
        endpoint = "/api/v1/orders"
        headers = self._headers("DELETE", endpoint)
        r = await self.client.delete(f"{self.base}{endpoint}", headers=headers)
        r.raise_for_status()

    async def set_leverage_isolated(self, symbol: str, leverage: int) -> None:
        # TODO: Confirm endpoint behavior across account types.
        await self._private_post(
            "/api/v1/position/margin/auto-deposit-status",
            {"symbol": symbol, "status": False},
        )
        await self._private_post(
            "/api/v1/position/risk-limit-level/change",
            {"symbol": symbol, "level": 1},
        )
        _ = leverage
