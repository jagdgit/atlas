# Screener / fundamentals import (IIP.3)

Atlas does **not** scrape Screener.in HTML. Operator-exported CSV/JSON becomes durable evidence.

## What gets stored

- Path: `{data}/investment/fundamentals/{program_id}.json` (usually `/data/atlas_data/...`)
- Schema fields: ROE, ROCE, ROIC, debt_to_equity, PE, PB, FCF, margins, growth, promoter %, pledge, price, shares, sector
- Missing fields stay missing — `evidence_sufficiency` is `missing` / `weak` / `sufficient`
- Import also merges a **screener snapshot** so ranking quality leaves pure seeds
- Discovery overlays the same store on quality gates

## Ways to import

### 1. Invest intel UI

1. Open **Invest intel**
2. Paste CSV or JSON into **Fundamentals import**
3. Click **Import paste**
4. Optional: check **push to IRA** to apply each row as an operator snapshot (estimated confidence; no auto section refresh unless you set `auto_refresh` via API)

### 2. API

```http
POST /v1/market/fundamentals/import
Authorization: Bearer <ATLAS_API_KEYS>
Content-Type: application/json

{ "csv": "symbol,roe,roce,debt_to_equity\nINFY,28,32,0.1\n" }
```

JSON:

```json
{ "rows": [ { "symbol": "INFY", "roe": 28, "roce": 32, "debt_to_equity": 0.1 } ] }
```

Optional: `"push_to_ira": true`, `"evidence_confidence": "estimated"`.

Status: `GET /v1/market/fundamentals`

### 3. Drop folder

1. Copy `.csv` / `.json` into `{data}/imports/fundamentals/`
2. Click **Ingest drop folder** on Invest intel, or `POST /v1/market/fundamentals/import-drop`
3. Processed files move to `imports/fundamentals/done/`

## Screener.in export tips (ToS-safe)

1. Build a screen / watchlist in the browser (your account)
2. Use Screener’s **export / download** (CSV) — do not automate page scraping
3. Ensure a **symbol** column (`Symbol`, `NSE Code`, or Yahoo-style `INFY.NS`)
4. Prefer columns Atlas aliases: ROE, ROCE, Debt to equity, Operating margin, Promoter holding, Sales growth, PE, FCF
5. Paste or drop the file into Atlas

Ratios may be percent (28) or fraction (0.28); Atlas normalizes to percent in the store and to fraction for ranking ROE/ROIC when needed.

## Honesty rules

- Import ≠ verified filings — treat as convenience evidence (`estimated` when pushed to IRA)
- Coverage of imported fields ≠ investment confidence
- Prefer annual/quarterly PDFs (IIP.4) for stronger dossier sections
