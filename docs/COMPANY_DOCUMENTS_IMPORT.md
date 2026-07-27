# Company documents import (IIP.4)

Operator-uploaded annual reports, quarterlies, decks, and transcripts become **extracted claims** on IRA dossiers. Atlas does **not** scrape exchange sites.

## Ways to import

### Invest intel UI

1. Open **Invest intel** → **Company documents (IIP.4)**
2. Enter symbol + kind
3. Either host path to a PDF, or paste an excerpt / transcript
4. **Import to IRA** — extracts guidance / risks / KPIs and attaches evidence

### Drop folder

Name files:

```text
SYMBOL__kind__period.pdf
INFY__annual__FY25.pdf
BEL__quarterly__Q3FY26.pdf
TCS__deck__investor_day.pdf
RELIANCE__transcript__earnings_Q3.txt
```

Kinds: `annual` (A), `quarterly` (B), `presentation` / `deck` (C), `transcript` / `earnings_call` (D)

Drop into `{data}/imports/company_documents/` then click **Ingest drop folder**.

### API

```http
POST /v1/market/company-documents/import
{ "symbol": "INFY", "kind": "annual", "text": "…guidance… ROCE 22% …" }
```

Or `"path": "/path/to/report.pdf"`. List: `GET /v1/market/company-documents`.

## What happens

1. PDF text layer (then optional OCR if weak)
2. Deterministic extract: guidance, risks, KPI regexes (ROE/ROCE/D/E/margins/FCF/…)
3. Durable manifest under `investment/company_documents/{program}/{SYMBOL}/`
4. Filing ref + **present** evidence on growth / risks / management / …
5. Parsed numbers optionally merge as estimated operator snapshot
6. Incremental dossier refresh

Missing text → honest empty extract / CapabilityGap — never invent MoS or FCF.

## Honesty

- Extracted claims ≠ audited line items
- Coverage / research quality / investment confidence stay independent
- Prefer official PDFs you already have; refs-only path remains `POST /v1/market/research/{symbol}/filings`
