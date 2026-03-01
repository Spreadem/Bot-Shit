# Risk Notes: Neutral Funding Arbitrage

## Why liquidation can still happen in "neutral" strategies

Even when long and short notionals are matched, liquidation risk is not zero:

1. **Cross-exchange basis divergence**
   - Mark prices can diverge temporarily between venues.
   - One leg can move against you faster than the hedge updates.

2. **Latency and sequencing gap risk**
   - In sequential entry, the first leg can fill while second leg is delayed or rejected.
   - During that gap, you are directional.

3. **Contract multiplier / lot-size mismatch**
   - Bybit and KuCoin may require different quantity increments.
   - Imperfect rounding creates persistent small directional drift.

4. **Funding timing mismatch and rate resets**
   - Next funding windows and calculations can differ by venue.
   - The expected spread can compress before settlement.

5. **Mark price / index methodology differences**
   - Liquidation is based on mark price, not last trade.
   - Exchange-specific mark formulas can trigger liq unexpectedly.

6. **Operational and API faults**
   - Stale market data or failed cancels can leave unhedged exposure.
   - Maintenance windows can block corrective actions.

## Liquidation edge cases to monitor

- One leg reports isolated margin but leverage/mode update failed.
- Position mismatch (ghost/partial fill) between local state and exchange state.
- Large spread widening around macro events.
- Sudden fee tier changes that reduce expected net carry.

## Why this bot does not rely on classic stop-loss

In neutral carry strategies, stop-loss has drawbacks:

- **Stop-loss can crystallize temporary basis noise** rather than true risk.
- **Trigger asymmetry:** one leg can stop out while hedge remains open, creating directional exposure.
- **Liquidity sweeps:** thin books can trigger stops at poor prices and worsen slippage.

Instead, this bot uses **risk rails better suited for market-neutral carry**:

- liquidation buffer thresholds (`MIN_LIQ_BUFFER_PCT`)
- notional drift limits (`MAX_NOTIONAL_DRIFT_PCT`)
- spread hysteresis exit (`EXIT_DIFF_BPS`)
- hard circuit breaker on data/API anomalies
- max drawdown / max daily loss portfolio constraints

## Practical recommendations

- Keep leverage conservative (2–3x to start).
- Cap per-symbol and total notional tightly.
- Prefer maker-hybrid entries and avoid forcing fills during volatility spikes.
- Review exchange maintenance schedules and status APIs before sessions.
