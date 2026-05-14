"""CAS PDF parser and importer using casparser library."""
import json
import logging
from datetime import datetime

try:
    import casparser
except ImportError:
    casparser = None

from db.database import get_connection

logger = logging.getLogger(__name__)

# Transaction types that indicate money going OUT (redemption/sell)
SELL_TX_TYPES = {"REDEMPTION", "SWITCH_OUT", "SWITCH_OUT_MERGER"}

# Transaction types that indicate money going IN (purchase/invest)
BUY_TX_TYPES = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER"}


def parse_cas(pdf_path: str, password: str) -> dict:
    """Parse CAS PDF and return structured data dict."""
    if casparser is None:
        raise ImportError(
            "casparser is not installed. Install it with: pip install casparser\n"
            "Alternatively, use the Excel CAS import: python cli.py import-cas --pdf <excel-file.xlsx>"
        )
    logger.info(f"Parsing CAS PDF: {pdf_path}")
    data = casparser.read_cas_pdf(pdf_path, password)
    logger.info(
        f"Parsed CAS: {data.get('cas_type', 'UNKNOWN')} | "
        f"Period: {data.get('statement_period', {}).get('from', '?')} to "
        f"{data.get('statement_period', {}).get('to', '?')}"
    )
    return data


def import_cas_to_db(parsed_data: dict, detect_sells: bool = True):
    """Import parsed CAS data into the database.

    - Upserts holdings
    - Inserts transactions (idempotent via UNIQUE constraint)
    - Optionally detects new sell/redemption transactions
    """
    conn = get_connection()
    cursor = conn.cursor()

    folios = parsed_data.get("folios", [])
    total_schemes = 0
    total_transactions = 0
    new_sells_detected = 0

    for folio_data in folios:
        folio = folio_data.get("folio", "")
        amc = folio_data.get("amc", "")
        pan = folio_data.get("PAN", "")

        for scheme_data in folio_data.get("schemes", []):
            scheme_name = scheme_data.get("scheme", "")
            isin = scheme_data.get("isin", "")
            amfi_code = scheme_data.get("amfi", "")
            rta_code = scheme_data.get("rta_code", "")
            advisor = scheme_data.get("advisor", "")
            scheme_type = scheme_data.get("type", "")
            close_units = scheme_data.get("close", 0) or 0

            # Valuation data
            valuation = scheme_data.get("valuation", {}) or {}
            val_nav = valuation.get("nav")
            val_value = valuation.get("value")
            val_cost = valuation.get("cost", 0) or 0

            is_active = 1 if close_units > 0 else 0

            # Upsert holding
            cursor.execute("""
                INSERT INTO holdings (folio, amc, scheme_name, isin, amfi_code,
                    rta_code, scheme_type, advisor, current_units, latest_nav,
                    latest_value, cost_value, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(folio, scheme_name) DO UPDATE SET
                    amc = excluded.amc,
                    isin = COALESCE(excluded.isin, holdings.isin),
                    amfi_code = COALESCE(excluded.amfi_code, holdings.amfi_code),
                    rta_code = COALESCE(excluded.rta_code, holdings.rta_code),
                    scheme_type = excluded.scheme_type,
                    advisor = excluded.advisor,
                    current_units = excluded.current_units,
                    latest_nav = excluded.latest_nav,
                    latest_value = excluded.latest_value,
                    cost_value = excluded.cost_value,
                    is_active = excluded.is_active,
                    updated_at = CURRENT_TIMESTAMP
            """, (folio, amc, scheme_name, isin, amfi_code, rta_code,
                  scheme_type, advisor, close_units, val_nav, val_value,
                  val_cost, is_active))

            # Get holding ID
            cursor.execute(
                "SELECT id FROM holdings WHERE folio = ? AND scheme_name = ?",
                (folio, scheme_name)
            )
            holding_row = cursor.fetchone()
            holding_id = holding_row["id"] if holding_row else None

            # Insert transactions
            for tx in scheme_data.get("transactions", []):
                tx_date = tx.get("date", "")
                if isinstance(tx_date, datetime):
                    tx_date = tx_date.strftime("%Y-%m-%d")
                elif isinstance(tx_date, str) and tx_date:
                    # Try to normalize date format
                    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                        try:
                            tx_date = datetime.strptime(tx_date, fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue

                tx_type = tx.get("type", "MISC")
                tx_amount = tx.get("amount", 0) or 0
                tx_units = tx.get("units", 0) or 0
                tx_nav = tx.get("nav", 0) or 0
                tx_balance = tx.get("balance", 0) or 0
                tx_desc = tx.get("description", "")
                tx_div_rate = tx.get("dividend_rate")

                try:
                    cursor.execute("""
                        INSERT INTO transactions (holding_id, folio, scheme_name,
                            date, description, amount, units, nav, balance,
                            tx_type, dividend_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(folio, scheme_name, date, amount, units, tx_type)
                        DO NOTHING
                    """, (holding_id, folio, scheme_name, tx_date, tx_desc,
                          tx_amount, tx_units, tx_nav, tx_balance, tx_type,
                          tx_div_rate))
                    if cursor.rowcount > 0:
                        total_transactions += 1

                        # Auto-detect sells from CAS
                        if detect_sells and tx_type in SELL_TX_TYPES and tx_units != 0:
                            sell_units = abs(tx_units)
                            sell_nav = tx_nav
                            sell_value = abs(tx_amount)

                            # Check if this sell is already recorded
                            cursor.execute("""
                                SELECT id FROM sell_decisions
                                WHERE scheme_name = ? AND sell_date = ?
                                AND sell_units = ? AND source = 'cas_detected'
                            """, (scheme_name, tx_date, sell_units))

                            if not cursor.fetchone():
                                cursor.execute("""
                                    INSERT INTO sell_decisions (holding_id,
                                        scheme_name, amfi_code, sell_date,
                                        sell_units, sell_nav, sell_value,
                                        reason, source)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'cas_detected')
                                """, (holding_id, scheme_name, amfi_code,
                                      tx_date, sell_units, sell_nav, sell_value,
                                      f"Auto-detected {tx_type} from CAS"))
                                new_sells_detected += 1

                except Exception as e:
                    logger.warning(f"Failed to insert transaction: {e}")
                    continue

            total_schemes += 1

    conn.commit()
    conn.close()

    summary = {
        "schemes_imported": total_schemes,
        "transactions_imported": total_transactions,
        "sells_detected": new_sells_detected,
    }

    print(f"\n{'='*50}")
    print(f"CAS Import Summary")
    print(f"{'='*50}")
    print(f"Schemes processed : {total_schemes}")
    print(f"New transactions  : {total_transactions}")
    print(f"Sells detected    : {new_sells_detected}")
    print(f"{'='*50}\n")

    return summary


def import_cas_file(pdf_path: str, password: str, detect_sells: bool = True):
    """End-to-end: parse CAS PDF and import to DB."""
    parsed = parse_cas(pdf_path, password)
    return import_cas_to_db(parsed, detect_sells=detect_sells)


def get_holdings_summary():
    """Get a summary of all holdings in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT h.*,
            (SELECT COUNT(*) FROM transactions t WHERE t.holding_id = h.id) as tx_count
        FROM holdings h
        ORDER BY h.is_active DESC, h.latest_value DESC NULLS LAST
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows
