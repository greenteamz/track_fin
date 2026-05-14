"""Parse CDSL monthly statement PDF to extract stock holdings."""
import logging
import re

import pdfplumber

from db.database import get_connection

logger = logging.getLogger(__name__)

# ISIN to NSE ticker mapping for common Indian stocks
# This will be auto-populated from the parsed data + manual mapping
ISIN_TO_TICKER = {
    "INE274Y01021": "AJAXENGG.NS",
    "INE818A01017": "SELAN.NS",
    "INE006I01046": "ASTRAL.NS",
    "INE00E101023": "BIKAJI.NS",
    "INE0LMW01024": "CELLO.NS",
    "INE510A01028": "ENGINERSIN.NS",
    "INE0NHL23019": "INDUSINVIT.NS",
    "INE351F01018": "JPPOWER.NS",
    "INE274J01014": "OIL.NS",
    "INE785M01021": "PCJEWELLER.NS",
    "INE703B01027": "RATNAMANI.NS",
    "INE040H01021": "SUZLON.NS",
    "INE092A01019": "TATACHEM.NS",
    "INE1TAE01010": "TATAMOTORS.NS",
    "INE155A01022": "TATAMTRDVR.NS",
    "INE245A01021": "TATAPOWER.NS",
    "INE010J01012": "TEJASNET.NS",
}


def parse_cdsl_statement(pdf_path: str) -> list[dict]:
    """Parse CDSL monthly statement PDF and extract stock holdings.

    Returns list of dicts with: isin, security_name, quantity, free_balance, market_price, value
    """
    logger.info(f"Parsing CDSL statement: {pdf_path}")
    pdf = pdfplumber.open(pdf_path)

    holdings = []
    seen_isins = set()

    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue

            # Check if this is a stock holdings table (has ISIN header)
            header = str(table[0]) if table[0] else ""
            if "ISIN" not in header or "Security" not in header:
                continue
            if "Current" not in header and "Bal" not in header:
                continue

            # Parse data rows (skip header)
            for row in table[1:]:
                if not row or not row[0]:
                    continue

                isin = str(row[0]).strip()
                # Validate ISIN format (INExxxxxxxxxx)
                if not re.match(r"^INE[A-Z0-9]{9,10}$", isin):
                    continue

                if isin in seen_isins:
                    continue
                seen_isins.add(isin)

                # Clean security name (remove newlines, Hindi text)
                security_name = str(row[1]).strip() if row[1] else ""
                # Take only the first line (English name)
                security_name = security_name.split("\n")[0].strip()
                # Clean up common suffixes
                security_name = re.sub(r"\s*#\s*$", "", security_name)

                # Parse numeric fields
                quantity = _parse_number(row[2])
                free_balance = _parse_number(row[6]) if len(row) > 6 else quantity
                market_price = _parse_number(row[7]) if len(row) > 7 else 0
                value = _parse_number(row[8]) if len(row) > 8 else 0

                if quantity > 0:
                    holdings.append({
                        "isin": isin,
                        "security_name": security_name,
                        "quantity": quantity,
                        "free_balance": free_balance,
                        "market_price": market_price,
                        "value": value,
                        "ticker": ISIN_TO_TICKER.get(isin, ""),
                    })

    pdf.close()
    logger.info(f"Parsed {len(holdings)} stock holdings from CDSL statement")
    return holdings


def _parse_number(val) -> float:
    """Parse a number from table cell, handling commas and dashes."""
    if not val:
        return 0
    s = str(val).strip().replace(",", "").replace("--", "0")
    # Extract first number from string
    match = re.search(r"[\d.]+", s)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return 0
    return 0


def import_cdsl_to_db(pdf_path: str):
    """Parse CDSL statement and import stock holdings into database."""
    holdings = parse_cdsl_statement(pdf_path)
    if not holdings:
        print("No stock holdings found in CDSL statement.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    imported = 0
    for h in holdings:
        cursor.execute("""
            INSERT INTO stock_holdings (isin, security_name, ticker, quantity,
                avg_price, invested_value, latest_price, latest_value, free_balance,
                dp_id, client_id, is_active, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, '', '', 1, CURRENT_TIMESTAMP)
            ON CONFLICT(isin) DO UPDATE SET
                security_name = excluded.security_name,
                ticker = CASE WHEN excluded.ticker != '' THEN excluded.ticker
                              ELSE stock_holdings.ticker END,
                quantity = excluded.quantity,
                latest_price = excluded.latest_price,
                latest_value = excluded.latest_value,
                free_balance = excluded.free_balance,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
        """, (h["isin"], h["security_name"], h["ticker"],
              h["quantity"], h["market_price"], h["value"], h["free_balance"]))
        imported += 1

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print(f"CDSL Stock Import Summary")
    print(f"{'='*50}")
    print(f"Stocks imported: {imported}")
    print(f"{'='*50}")
    print(f"\n{'Stock':<35} {'Qty':>8} {'Price':>10} {'Value':>12}")
    print("─" * 70)
    for h in holdings:
        print(f"{h['security_name'][:34]:<35} {h['quantity']:>8.0f} "
              f"₹{h['market_price']:>9,.2f} ₹{h['value']:>11,.2f}")
    total = sum(h["value"] for h in holdings)
    print("─" * 70)
    print(f"{'TOTAL':<35} {'':>8} {'':>10} ₹{total:>11,.2f}")
    print()

    return {"stocks_imported": imported, "total_value": total}
