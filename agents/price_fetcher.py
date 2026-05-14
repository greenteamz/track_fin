"""Daily NAV and stock price fetcher."""
import logging
import time
from datetime import date, datetime

import yfinance as yf
from mftool import Mftool

from config import STOCK_TICKERS
from db.database import get_connection

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def _retry(func, *args, retries=MAX_RETRIES, delay=RETRY_DELAY, **kwargs):
    """Retry a function with exponential backoff."""
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {retries} attempts failed: {e}")
                raise


def fetch_all_nav():
    """Fetch latest NAV for all active holdings and store in daily_prices."""
    conn = get_connection()
    cursor = conn.cursor()

    # Get all active holdings with AMFI codes
    cursor.execute("""
        SELECT DISTINCT amfi_code, scheme_name
        FROM holdings
        WHERE is_active = 1 AND amfi_code IS NOT NULL AND amfi_code != ''
    """)
    holdings = cursor.fetchall()

    if not holdings:
        print("No active holdings with AMFI codes found. Import CAS first.")
        conn.close()
        return

    amfi_codes = [h["amfi_code"] for h in holdings]
    scheme_map = {h["amfi_code"]: h["scheme_name"] for h in holdings}
    today = date.today().isoformat()

    print(f"\nFetching NAV for {len(amfi_codes)} schemes...")
    mf = Mftool()

    # Use bulk quotes for faster fetching
    try:
        quotes = _retry(mf.get_bulk_quotes, amfi_codes)
    except Exception as e:
        logger.error(f"Bulk quote fetch failed: {e}")
        # Fallback to individual fetching
        quotes = {}
        for code in amfi_codes:
            try:
                q = _retry(mf.get_scheme_quote, code)
                if q:
                    quotes[code] = q
            except Exception as ex:
                logger.warning(f"Failed to fetch NAV for {code}: {ex}")

    fetched = 0
    for code in amfi_codes:
        quote = quotes.get(code) or quotes.get(str(code))
        if not quote:
            logger.warning(f"No quote for AMFI {code} ({scheme_map.get(code, '?')})")
            continue

        nav_str = quote.get("nav", "0")
        try:
            nav = float(nav_str)
        except (ValueError, TypeError):
            logger.warning(f"Invalid NAV '{nav_str}' for {code}")
            continue

        scheme_name = quote.get("scheme_name", scheme_map.get(code, ""))

        # Insert into daily_prices (idempotent)
        cursor.execute("""
            INSERT INTO daily_prices (amfi_code, scheme_name, date, nav)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(amfi_code, date) DO UPDATE SET nav = excluded.nav
        """, (str(code), scheme_name, today, nav))

        # Update holdings with latest NAV
        cursor.execute("""
            UPDATE holdings
            SET latest_nav = ?, latest_value = current_units * ?, updated_at = CURRENT_TIMESTAMP
            WHERE amfi_code = ? AND is_active = 1
        """, (nav, nav, str(code)))

        fetched += 1

    conn.commit()
    conn.close()
    print(f"✓ Fetched NAV for {fetched}/{len(amfi_codes)} schemes (date: {today})")
    return fetched


def fetch_stock_prices():
    """Fetch latest stock prices via yfinance for all stocks in stock_holdings + config."""
    conn = get_connection()
    cursor = conn.cursor()
    today = date.today().isoformat()

    # Get tickers from stock_holdings table
    cursor.execute("""
        SELECT DISTINCT ticker, isin, security_name, quantity
        FROM stock_holdings
        WHERE is_active = 1 AND ticker IS NOT NULL AND ticker != ''
    """)
    db_stocks = cursor.fetchall()

    # Combine with config tickers
    all_tickers = set(STOCK_TICKERS)
    ticker_to_holding = {}
    for row in db_stocks:
        all_tickers.add(row["ticker"])
        ticker_to_holding[row["ticker"]] = {
            "isin": row["isin"],
            "name": row["security_name"],
            "quantity": row["quantity"],
        }

    if not all_tickers:
        print("No stock tickers to fetch.")
        conn.close()
        return 0

    print(f"\nFetching stock prices for {len(all_tickers)} stocks...")
    fetched = 0

    for ticker in sorted(all_tickers):
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if hist.empty:
                logger.warning(f"No data for {ticker}")
                continue

            close_price = float(hist["Close"].iloc[-1])
            volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist else 0

            cursor.execute("""
                INSERT INTO stock_prices (ticker, date, close_price, volume)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    close_price = excluded.close_price,
                    volume = excluded.volume
            """, (ticker, today, close_price, volume))

            # Update stock_holdings with latest price
            if ticker in ticker_to_holding:
                info = ticker_to_holding[ticker]
                latest_value = info["quantity"] * close_price
                cursor.execute("""
                    UPDATE stock_holdings
                    SET latest_price = ?, latest_value = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE ticker = ?
                """, (close_price, latest_value, ticker))

            fetched += 1
            print(f"  {ticker}: ₹{close_price:,.2f}")

        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✓ Fetched prices for {fetched}/{len(all_tickers)} stocks")
    return fetched


def take_portfolio_snapshot():
    """Calculate and store daily portfolio snapshot."""
    conn = get_connection()
    cursor = conn.cursor()
    today = date.today().isoformat()

    # Total invested in MF: use cost_value from holdings (more reliable than summing transactions)
    cursor.execute("""
        SELECT COALESCE(SUM(cost_value), 0) as total
        FROM holdings
        WHERE is_active = 1
    """)
    mf_invested = cursor.fetchone()["total"]

    # Current value of active MF holdings
    cursor.execute("""
        SELECT COALESCE(SUM(latest_value), 0) as total
        FROM holdings
        WHERE is_active = 1
    """)
    mf_value = cursor.fetchone()["total"]

    # Current value of active stock holdings
    cursor.execute("""
        SELECT COALESCE(SUM(latest_value), 0) as total
        FROM stock_holdings
        WHERE is_active = 1
    """)
    stock_value = cursor.fetchone()["total"]

    # Also add stock invested value to net_invested
    cursor.execute("""
        SELECT COALESCE(SUM(invested_value), 0) as total
        FROM stock_holdings
        WHERE is_active = 1
    """)
    stock_invested = cursor.fetchone()["total"]

    net_invested = mf_invested + stock_invested
    current_value = mf_value + stock_value

    total_pnl = current_value - net_invested

    # Day change (compare with previous snapshot)
    cursor.execute("""
        SELECT total_current_value FROM portfolio_snapshots
        ORDER BY date DESC LIMIT 1
    """)
    prev = cursor.fetchone()
    prev_value = prev["total_current_value"] if prev else current_value
    day_change = current_value - prev_value

    cursor.execute("""
        INSERT INTO portfolio_snapshots (date, total_invested, total_current_value,
            total_pnl, day_change)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_invested = excluded.total_invested,
            total_current_value = excluded.total_current_value,
            total_pnl = excluded.total_pnl,
            day_change = excluded.day_change
    """, (today, net_invested, current_value, total_pnl, day_change))

    conn.commit()
    conn.close()

    print(f"\n{'─'*40}")
    print(f"Portfolio Snapshot ({today})")
    print(f"{'─'*40}")
    print(f"Net Invested  : ₹{net_invested:>12,.2f}")
    print(f"Current Value : ₹{current_value:>12,.2f}")
    print(f"Total P&L     : ₹{total_pnl:>12,.2f}")
    print(f"Day Change    : ₹{day_change:>12,.2f}")
    print(f"{'─'*40}")

    return {
        "date": today,
        "total_invested": net_invested,
        "total_current_value": current_value,
        "total_pnl": total_pnl,
        "day_change": day_change,
    }


def run_daily_fetch():
    """Run the complete daily fetch routine."""
    print(f"\n{'='*50}")
    print(f"Daily Fetch — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    fetch_all_nav()
    fetch_stock_prices()
    take_portfolio_snapshot()

    print(f"\n✓ Daily fetch complete at {datetime.now().strftime('%H:%M:%S')}")
