# 📊 Mutual Fund Decision Tracker

Track your mutual fund portfolio, log sell decisions, and evaluate whether selling was the right call — with automated daily NAV tracking and a beautiful Streamlit dashboard.

## Features

- **CAS PDF Import** — Parse your Consolidated Account Statement from CAMS/KFintech using `casparser`
- **Daily NAV Tracking** — Automated price fetching via `mftool` (mutual funds) and `yfinance` (stocks)
- **Sell Decision Logging** — Manual CLI logging + auto-detection from CAS re-imports
- **Decision Evaluation** — Compare "what if I held" vs "what I got" at 7/30/90/180 day intervals
- **Streamlit Dashboard** — 4-tab dashboard with Plotly charts, XIRR calculations, and shadow portfolio
- **Background Scheduler** — Local scheduler runs daily at 7:30 AM IST
- **Semi-Auto CAS Download** — Selenium-based MFCentral login (you click reCAPTCHA, script does the rest)

## Quick Start

### 1. Clone & Install

```bash
cd sell-decision-tracker
pip install -r requirements.txt
```

### 2. Set Up Environment Variables

```bash
# Copy the template
copy .env.example .env    # Windows
# cp .env.example .env    # Linux/Mac

# Edit .env with your credentials
notepad .env
```

Fill in your `.env`:
```
MF_PAN=YOUR_PAN_HERE
MF_CAS_PASSWORD=your_cas_pdf_password
CAS_PDF_PATH=./cas-statement.pdf
STOCK_TICKERS=OIL.NS,INDUSINDBK.NS
DB_PATH=./portfolio.db
```

### 3. Download CAS from MFCentral

#### Manual Download (Recommended first time)

1. Go to [mfcentral.com](https://www.mfcentral.com)
2. Click **"Sign In"**
3. Enter your **PAN** in the "Enter PAN / PEKRN" field
4. Toggle to **Password** mode (not OTP)
5. Enter your **password**
6. Click the **"I'm not a robot"** checkbox
7. Click **"Sign In"**
8. Navigate to **Reports** → **CAS** (or similar section)
9. Select **Detailed** statement type
10. Select date range (ideally from your first investment to today)
11. Set the **PDF password** (remember this — it goes in `MF_CAS_PASSWORD`)
12. Download the CAS PDF
13. Save it to your project folder as `cas-statement.pdf`

#### Semi-Automated Download

```bash
python cli.py download-cas
```
This opens a browser, fills PAN + password, and waits for you to click the reCAPTCHA checkbox.

### 4. Import CAS

```bash
python cli.py import-cas --pdf cas-statement.pdf
```

### 5. Fetch Latest NAV

```bash
python cli.py fetch-nav
```

### 6. Launch Dashboard

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## CLI Commands

| Command | Description |
|---------|-------------|
| `python cli.py import-cas --pdf <path>` | Import CAS PDF into database |
| `python cli.py download-cas` | Download CAS from MFCentral via browser |
| `python cli.py sell --scheme "name" --units N --price P --reason "text"` | Log a sell decision |
| `python cli.py fetch-nav` | Fetch latest NAV for all holdings |
| `python cli.py evaluate` | Run decision evaluation engine |
| `python cli.py status` | Print portfolio summary to terminal |

### Logging a Sell Decision

```bash
python cli.py sell \
  --scheme "HDFC Flexi Cap Fund" \
  --units 100 \
  --price 45.50 \
  --reason "Need cash for real estate" \
  --date 2025-01-15
```

The `--scheme` flag does fuzzy matching against your imported holdings. If multiple matches are found, you'll be prompted to pick one.

## Daily Scheduler

Run the background scheduler to auto-fetch NAV at 7:30 AM IST:

```bash
python scheduler.py
```

Options:
- `python scheduler.py --once` — Run immediately and exit (for testing)
- `python scheduler.py --time 09:00` — Change the daily run time

## Dashboard Tabs

### 📈 Active Holdings
- All current MF holdings with units, NAV, current value, P&L
- XIRR calculation per scheme (using `pyxirr`)
- Portfolio allocation pie chart

### 📤 Withdrawn/Sold
- Shadow portfolio: "If I had held, my value would be ₹X"
- Comparison bar chart (sold value vs hypothetical value)

### 🎯 Decision Report
- Each sell decision with 7d/30d/90d/6m verdicts
- Decision accuracy pie chart
- NAV movement charts with sell points marked

### 📊 Portfolio Summary
- KPI cards: Total Invested, Current Value, P&L, Day Change
- Portfolio value over time
- Daily P&L bar chart
- Per-fund NAV trends (multi-select comparison)
- Per-fund returns bar chart

## Decision Verdicts

| Verdict | Condition | Meaning |
|---------|-----------|---------|
| ✅ GOOD CALL | Fund dropped >3% after sell | You sold at the right time |
| ⚠️ MISSED GAINS | Fund rose >3% after sell | You missed potential gains |
| ➖ NEUTRAL | Within ±3% | No significant impact |

Alerts (written to `alerts.md`):
- Fund drops 5%+ after sell → **"✅ Confirmed good decision"**
- Fund rises 10%+ after sell → **"⚠️ Review: missed gains"**

## Adding Stock Tickers

Edit your `.env` file:
```
STOCK_TICKERS=OIL.NS,INDUSINDBK.NS,RELIANCE.NS,TCS.NS
```

Use Yahoo Finance ticker format (`.NS` suffix for NSE, `.BO` for BSE).

## Project Structure

```
sell-decision-tracker/
├── app.py                  # Streamlit dashboard
├── cli.py                  # CLI for all operations
├── config.py               # Environment vars & settings
├── scheduler.py            # Background daily scheduler
├── db/
│   ├── database.py         # SQLite schema & connection
│   └── models.py           # Data models
├── agents/
│   ├── cas_parser.py       # CAS PDF import logic
│   ├── cas_downloader.py   # Selenium MFCentral downloader
│   ├── price_fetcher.py    # NAV & stock price fetcher
│   └── evaluator.py        # Decision evaluation engine
├── .env.example            # Environment template
├── requirements.txt        # Python dependencies
├── withdrawals.json        # Sell log (human-readable)
├── alerts.md               # Auto-generated alerts
└── portfolio.db            # SQLite database (auto-created)
```

## Tech Stack

- **Python 3.11+**
- `casparser` — CAS PDF parsing
- `mftool` — Mutual fund NAV from AMFI
- `yfinance` — Stock prices
- `pyxirr` — XIRR calculation (Rust-powered)
- `streamlit` + `plotly` — Dashboard & charts
- `selenium` — Browser automation
- `sqlite3` — Local database
- `schedule` — Background job scheduler

## Troubleshooting

**"No active holdings found"** — Import your CAS PDF first: `python cli.py import-cas --pdf <path>`

**"AMFI code not found"** — Update the ISIN database: `casparser-isin --update`

**NAV fetch returns 0 schemes** — Check that your holdings have valid AMFI codes. Re-import CAS if needed.

**Selenium fails** — Install Chrome or Edge browser. The script auto-downloads the driver via `webdriver-manager`.

**XIRR shows N/A** — Needs at least 2 transactions (buy + current value) to calculate XIRR.
