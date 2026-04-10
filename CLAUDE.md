# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korea Investment Securities (KIS) Open API sample code repository. Contains REST/WebSocket API wrappers for Korean and overseas stock trading, organized as:
- `examples_llm/` — Single-function API samples (one file per API endpoint), optimized for LLM reference
- `examples_user/` — Integrated example applications by product type
- `stocks_info/` — Stock master files (KOSPI/KOSDAQ code lists)
- `MCP/` — Model Context Protocol implementations

## Setup

**Package manager**: `uv` (requires Python 3.13+)

```bash
uv sync                    # Install dependencies
```

**Configuration**: Copy credentials into `kis_devlp.yaml`:
```yaml
my_app: "<실전투자 앱키>"
my_sec: "<실전투자 앱시크릿>"
paper_app: "<모의투자 앱키>"
paper_sec: "<모의투자 앱시크릿>"
my_htsid: "<HTS ID>"
my_acct_stock: "<계좌번호 앞 8자리>"
my_prod: "01"   # 01=종합, 03=선물옵션, 08=해외파생, 22=연금, 29=퇴직연금
```

**Telegram bot token**: Set `TELEGRAM_BOT_TOKEN` environment variable before running `bot.py`.

**Stock master files** (required before first use):
```bash
uv run stocks_info/kis_kospi_code_mst.py
uv run stocks_info/kis_kosdaq_code_mst.py
```

## Running Applications

```bash
# Telegram stock analysis bot
cd examples_user/telegram_stock_info
export TELEGRAM_BOT_TOKEN="<token>"
uv run bot.py

# Domestic stock examples
cd examples_user/domestic_stock
uv run domestic_stock_examples.py       # REST API
uv run domestic_stock_examples_ws.py    # WebSocket

# Overseas stock examples
cd examples_user/overseas_stock
uv run overseas_stock_examples.py
```

No test framework is configured. There is no linting setup.

## Architecture

### Authentication (`examples_user/kis_auth.py`)

Central auth module used by all examples. Call `ka.auth()` first, then `ka.getTREnv()` to get the trading environment. Tokens are cached locally for 1 day (files named `KIS[YYYYMMDD]`). Supports production and paper trading modes. WebSocket auth via `ka.auth_ws()`.

### API Wrappers (large files ~10K–14K lines each)

Each product type has a large `*_functions.py` file containing individual wrapper functions per API endpoint:
- `domestic_stock_functions.py` — domestic equities
- `overseas_stock_functions.py` — overseas equities
- `etfetn_functions.py` — ETF/ETN

These files live either in their product subdirectory under `examples_user/` or are copied into the telegram bot directory.

### Telegram Bot (`examples_user/telegram_stock_info/`)

`bot.py` — entry point, async event loop, routes user input to analyzers:
- Korean name or 6-digit code → `domestic_analyzer.py`
- `EXCHANGE:TICKER` format (e.g., `NAS:TSLA`) → `overseas_analyzer.py`
- `ETF:code` or 6-digit ETF code → `etf_analyzer.py`

Each analyzer: looks up stock code → fetches paginated historical data from KIS API → computes moving averages (MA5/10/20/60/120/240) and volume-based support/resistance levels → returns structured dict → `bot.py` formats as HTML for Telegram.

## Key Conventions

- All KIS API calls require a valid token from `kis_auth.py`; add 0.1–0.5s delay between calls to avoid rate limiting
- Pagination: most chart/price APIs return max 100 rows; loop with date params to get full history
- `kis_devlp.yaml` must not contain real credentials in version control (use environment variables or a gitignored local copy)
- The `examples_llm/` directory functions are the canonical reference for individual API signatures
