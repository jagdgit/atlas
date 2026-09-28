# Zerodha Kite Connect Live Market Data (OI-ZERODHA0)

**Status:** Scaffolding + callback login shipped. **LAB-LOOP0 Step 2:** `MarketReaderService` persists Zerodha historical into `market/bars` (daily) and `market/bars_intraday` (5m) with honest `provider=zerodha`. Yahoo daily prefers a live Kite session (labeled `zerodha_session_prefer`, not a silent Yahoo substitution). 10y Yahoo history stays on `history_provider`.  
**Scope:** Read-only LTP / quote / historical for NSE/BSE equities. **No live order placement** (Atlas P10).

### What Zerodha is *not*

Zerodha does **not** populate PE, FCF, ROE, debt, or MoS. Those fields live on the
fundamentals / IRA path (Yahoo enrich, Screener export, universe seed → IRA valuation).
See `atlas/investment/data_plane_contract.py` (`DATA_PROVIDER_CONTRACT`).

| Data | Provider | Destination | Required for |
|------|----------|-------------|--------------|
| LTP / OHLC / volume | Zerodha (primary live) | market marks / `bar_store` | technical |
| PE | Screener / Yahoo | fundamentals store | MoS |
| FCF | Yahoo / Screener / filings | fundamentals store | thesis / MoS |
| ROE / debt | Yahoo / universe seed | fundamentals store | thesis |
| MoS | IRA valuation | thesis packet | swing authorization |

Paid market API ≠ fundamental evidence. Completeness hydrates stores; it does not invent PE.

---

## Why

Yahoo chart APIs rate-limit (HTTP 429) during Indian RTH. Zerodha Kite Connect is the operator’s existing brokerage API path for authorized live marks.

## Auth (daily)

1. Set in `.env` (gitignored):
   - `ZERODHA_API_KEY`
   - `ZERODHA_API_SECRET`
   - `ZERODHA_REDIRECT_URL=http://127.0.0.1:8000/zerodha/callback`
2. In the **Zerodha Kite Connect developer console**, set the app Redirect URL to the
   **same** value (`http://127.0.0.1:8000/zerodha/callback`). If it is still
   `http://127.0.0.1:8000`, Atlas forwards `?request_token=` from `/` to the callback.
3. Install SDK: `pip install kiteconnect` (or `uv pip install kiteconnect`)
4. With Atlas serving on port 8000, open once per trading day:
   - Browser: http://127.0.0.1:8000/zerodha/login
   - Complete Zerodha login + 2FA
   - You land on `/zerodha/callback` with a success page (session saved under
     `{data_dir}/investment/zerodha/session.json`)
5. Check: http://127.0.0.1:8000/zerodha/status → `has_session: true`

**Why the UI opened before:** Redirect hit `/`, which only loaded the Atlas console and
ignored `request_token`. That is fixed.

## Usage

```python
feed.get_ltp(["RELIANCE.NS", "INFY.NS"])
feed.get_quote("RELIANCE.NS")
```

`MarketDataService.mark_for_symbol(..., allow_network=True)` prefers Zerodha LTP when a session is active, then bar_store, then Yahoo `fetch_fn`.

## Config

`config/defaults.yaml` → `market.zerodha_*` env key names. Secrets never live in YAML.
