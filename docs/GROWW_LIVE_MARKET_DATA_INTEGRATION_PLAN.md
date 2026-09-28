# Groww Live Market Data Integration Plan

**Status:** Proposed / Scaffolding ready  
**Target:** Atlas Indian Market Live Feeds & Swing/Intraday Data Plane  

---

## 1. Executive Summary & Objective

Atlas currently relies on Yahoo Finance (`yfinance` / chart APIs) as its default external market price source. While sufficient for historical backfills, Yahoo Finance imposes aggressive rate limits (HTTP 429), unpredictable scraping blocks, and lacks reliable real-time streaming during Indian market Regular Trading Hours (RTH, 09:15–15:30 IST).

The **Groww Trading API** provides official, low-latency, and high-throughput market data APIs for Indian equities (NSE & BSE Cash) and derivatives (F&O). Integrating Groww gives Atlas:
1. **Direct, authorized live prices** for NSE/BSE stocks with no scraping or rate-limit blocking.
2. **High throughput limits**: 10 requests/sec, 300 requests/min on REST endpoints; up to 1,000 instrument subscriptions on live WebSockets.
3. **Batch quote fetching**: Query up to 50 instruments simultaneously in a single round-trip.
4. **Reliable price marks for swing & intraday decision loops**: Eliminating `empty_live_feed` and `yahoo_cooldown` skip tags.

---

## 2. Groww API Overview & Specifications

### 2.1 SDK & Packaging
- **Package**: `growwapi` (v1.5.0, Python ≥ 3.9)
- **Install**: `pip install growwapi`
- **Pricing**: ₹499 + GST/month for Developer/Algo Trading API subscription.

### 2.2 Core Endpoints & Methods
| Category | Method | Description | Rate Limit |
| :--- | :--- | :--- | :--- |
| **LTP** | `GrowwAPI.get_ltp(segment, exchange_trading_symbols)` | Fetches Last Traded Price (supports batch up to 50 symbols) | 10 req/s, 300 req/min |
| **OHLC** | `GrowwAPI.get_ohlc(segment, exchange_trading_symbols)` | Fetches Open, High, Low, Close for stocks/derivatives | 10 req/s, 300 req/min |
| **Full Quote** | `GrowwAPI.get_quote(exchange, segment, trading_symbol)` | Fetches full market quote with depth, volume, OHLC | 10 req/s, 300 req/min |
| **Live Feed** | `GrowwFeed(groww_client).subscribe_live_data(...)` | WebSocket stream for real-time tick streaming & depth | Up to 1,000 instruments |

### 2.3 Authentication
- Uses OAuth 2.0 API Auth Token or API Key + Secret.
- Token refresh: Up to 150 access token generations per 24 hours via `/v1/token/api/access`.

---

## 3. Architecture & Integration in Atlas

### 3.1 Primary-Fallback Hierarchy
Atlas's `MarketDataService` routes mark resolution using the following order:

```text
[Request for Mark (e.g. RELIANCE.NS)]
             │
             ▼
   [1. In-Memory Cache] (TTL: 5 min)
             │ (Cache miss)
             ▼
   [2. Groww Market Feed (REST LTP)] ───► (If configured & market open)
             │ (Fallback if unconfigured/error)
             ▼
   [3. Local Bar Store] (Tip bar from disk)
             │ (Fallback if empty)
             ▼
   [4. Yahoo Finance API] (Strictly Rate-Gated)
```

### 3.2 Configuration (`config/defaults.yaml`)
```yaml
market:
  provider: groww # or 'yahoo'
  groww:
    enabled: true
    auth_token: ${GROWW_AUTH_TOKEN:-""}
    api_key: ${GROWW_API_KEY:-""}
    api_secret: ${GROWW_API_SECRET:-""}
    batch_size: 50
    rate_limit_per_sec: 10
```

### 3.3 Implementation Artifacts
1. **`atlas/investment/groww_feed.py`**:
   - `GrowwMarketFeed` class wrapping `GrowwAPI` / `GrowwFeed`.
   - Symbol normalization between Atlas (`SYMBOL.NS`) and Groww (`NSE_SYMBOL`).
   - Resilient error handling and structured mark generation.
2. **`atlas/investment/market_data_service.py`**:
   - Integrated `GrowwMarketFeed` as preferred live mark source during RTH.

---

## 4. Next Steps for Activation

1. **Obtain Groww API Credentials**:
   - Enable Trading API on the Groww account console.
   - Generate API Key / Auth Token.
2. **Environment Configuration**:
   - Export `GROWW_AUTH_TOKEN="<token>"` or place in Atlas settings.
3. **Install Package**:
   - Run `pip install growwapi` in Atlas's Python virtual environment.
