"""CLI interface for Mutual Fund Decision Tracker."""
import argparse
import json
import os
import sys
from datetime import datetime

# Fix Windows terminal encoding for Unicode output
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import init_db, get_connection
from config import CAS_PDF_PATH, MF_CAS_PASSWORD


def cmd_import_cas(args):
    """Import CAS PDF or Excel into database."""
    pdf_path = args.pdf or CAS_PDF_PATH
    password = args.password or MF_CAS_PASSWORD

    if not os.path.exists(pdf_path):
        print(f"Error: CAS file not found at {pdf_path}")
        print("Use --pdf to specify path, or set CAS_PDF_PATH in .env")
        return

    init_db()

    # Auto-detect Excel vs PDF
    if pdf_path.lower().endswith(('.xlsx', '.xls')):
        from agents.cas_excel_parser import import_cas_excel_to_db
        result = import_cas_excel_to_db(pdf_path)
    else:
        if not password:
            print("Error: CAS password required. Use --password or set MF_CAS_PASSWORD in .env")
            return
        from agents.cas_parser import import_cas_file
        result = import_cas_file(pdf_path, password)

    return result


def cmd_download_cas(args):
    """Download CAS from MFCentral and import."""
    from agents.cas_downloader import download_cas
    from agents.cas_parser import import_cas_file
    from config import MF_CAS_PASSWORD

    init_db()
    pdf_path = download_cas()

    if pdf_path and os.path.exists(pdf_path):
        print(f"\nImporting downloaded CAS: {pdf_path}")
        import_cas_file(pdf_path, MF_CAS_PASSWORD)


def cmd_email_cas(args):
    """Fetch CAS from email inbox and import."""
    from agents.email_cas_fetcher import fetch_cas_from_email
    from agents.cas_parser import import_cas_file
    from config import MF_CAS_PASSWORD

    init_db()
    pdf_path = fetch_cas_from_email(days_back=args.days)

    if pdf_path and os.path.exists(pdf_path):
        print(f"\nImporting CAS from email: {pdf_path}")
        import_cas_file(pdf_path, MF_CAS_PASSWORD)
    else:
        print("\nNo CAS PDF found. Request one from CAMS first:")
        print("  https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement")


def cmd_request_cas(args):
    """Request CAS from CAMS website, wait for email, then import."""
    from agents.email_cas_fetcher import request_and_fetch_cas
    from agents.cas_parser import import_cas_file
    from config import MF_CAS_PASSWORD

    init_db()
    pdf_path = request_and_fetch_cas()

    if pdf_path and os.path.exists(pdf_path):
        print(f"\nImporting CAS from email: {pdf_path}")
        import_cas_file(pdf_path, MF_CAS_PASSWORD)


def cmd_sell(args):
    """Log a manual sell/withdrawal decision."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # Try to find the holding
    cursor.execute("""
        SELECT id, amfi_code, scheme_name FROM holdings
        WHERE scheme_name LIKE ? OR amfi_code = ?
        LIMIT 5
    """, (f"%{args.scheme}%", args.scheme))
    matches = cursor.fetchall()

    if not matches:
        print(f"Warning: No holding found matching '{args.scheme}'.")
        print("Recording sell anyway (will link when CAS is imported).")
        holding_id = None
        amfi_code = None
        scheme_name = args.scheme
    elif len(matches) == 1:
        holding_id = matches[0]["id"]
        amfi_code = matches[0]["amfi_code"]
        scheme_name = matches[0]["scheme_name"]
        print(f"Matched: {scheme_name}")
    else:
        print("Multiple matches found:")
        for i, m in enumerate(matches):
            print(f"  [{i+1}] {m['scheme_name']} (AMFI: {m['amfi_code']})")
        choice = input("Enter number (or 0 to use as-is): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                holding_id = matches[idx]["id"]
                amfi_code = matches[idx]["amfi_code"]
                scheme_name = matches[idx]["scheme_name"]
            else:
                holding_id = None
                amfi_code = None
                scheme_name = args.scheme
        except ValueError:
            holding_id = None
            amfi_code = None
            scheme_name = args.scheme

    sell_date = args.date or datetime.now().strftime("%Y-%m-%d")
    sell_value = args.units * args.price

    cursor.execute("""
        INSERT INTO sell_decisions (holding_id, scheme_name, amfi_code,
            sell_date, sell_units, sell_nav, sell_value, reason, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')
    """, (holding_id, scheme_name, amfi_code, sell_date,
          args.units, args.price, sell_value, args.reason))

    conn.commit()

    # Also log to withdrawals.json
    withdrawal = {
        "scheme": scheme_name,
        "units": args.units,
        "price": args.price,
        "value": sell_value,
        "date": sell_date,
        "reason": args.reason,
        "timestamp": datetime.now().isoformat(),
    }

    withdrawals_file = "withdrawals.json"
    existing = []
    if os.path.exists(withdrawals_file):
        with open(withdrawals_file, "r") as f:
            existing = json.load(f)
    existing.append(withdrawal)
    with open(withdrawals_file, "w") as f:
        json.dump(existing, f, indent=2)

    conn.close()

    print(f"\n✓ Sell recorded:")
    print(f"  Scheme : {scheme_name}")
    print(f"  Units  : {args.units}")
    print(f"  NAV    : ₹{args.price:.2f}")
    print(f"  Value  : ₹{sell_value:,.2f}")
    print(f"  Date   : {sell_date}")
    print(f"  Reason : {args.reason}")


def cmd_fetch_nav(args):
    """Fetch latest NAV for all holdings."""
    from agents.price_fetcher import run_daily_fetch
    init_db()
    run_daily_fetch()


def cmd_import_stocks(args):
    """Import stocks from CDSL monthly statement PDF."""
    from agents.cdsl_parser import import_cdsl_to_db

    pdf_path = args.pdf
    if not os.path.exists(pdf_path):
        print(f"Error: CDSL statement not found at {pdf_path}")
        return

    init_db()
    import_cdsl_to_db(pdf_path)


def cmd_evaluate(args):
    """Run decision evaluation engine."""
    from agents.evaluator import run_evaluation
    init_db()
    run_evaluation()


def cmd_status(args):
    """Print portfolio summary."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # Holdings summary
    cursor.execute("""
        SELECT scheme_name, folio, current_units, latest_nav, latest_value,
               cost_value, amfi_code
        FROM holdings
        WHERE is_active = 1
        ORDER BY latest_value DESC NULLS LAST
    """)
    holdings = cursor.fetchall()

    print(f"\n{'='*80}")
    print(f"Portfolio Status — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    if holdings:
        total_value = 0
        total_cost = 0
        print(f"\n{'Scheme':<45} {'Units':>10} {'NAV':>10} {'Value (₹)':>12} {'P&L':>10}")
        print("─" * 90)
        for h in holdings:
            val = h["latest_value"] or 0
            cost = h["cost_value"] or 0
            pnl = val - cost if cost else 0
            total_value += val
            total_cost += cost
            name = h["scheme_name"][:44]
            nav_str = f"₹{h['latest_nav']:.2f}" if h["latest_nav"] else "N/A"
            pnl_str = f"₹{pnl:,.0f}"
            print(f"{name:<45} {h['current_units']:>10.3f} "
                  f"{nav_str:>10} "
                  f"₹{val:>11,.2f} "
                  f"{pnl_str:>10}")
        total_pnl_str = f"₹{total_value-total_cost:,.0f}"
        print("─" * 90)
        print(f"{'TOTAL':<45} {'':>10} {'':>10} ₹{total_value:>11,.2f} "
              f"{total_pnl_str:>10}")
    else:
        print("\nNo active MF holdings found. Import CAS first:")
        print("  python cli.py import-cas --pdf <path-to-cas.pdf>")

    # Stock holdings
    cursor.execute("""
        SELECT security_name, ticker, quantity, latest_price, latest_value
        FROM stock_holdings
        WHERE is_active = 1
        ORDER BY latest_value DESC NULLS LAST
    """)
    stocks = cursor.fetchall()

    if stocks:
        stock_total = 0
        print(f"\n{'Stock':<35} {'Ticker':<15} {'Qty':>8} {'Price':>10} {'Value (₹)':>12}")
        print("─" * 85)
        for s in stocks:
            val = s["latest_value"] or 0
            stock_total += val
            price_str = f"₹{s['latest_price']:.2f}" if s["latest_price"] else "N/A"
            print(f"{s['security_name'][:34]:<35} {(s['ticker'] or 'N/A'):<15} "
                  f"{s['quantity']:>8.0f} {price_str:>10} ₹{val:>11,.2f}")
        print("─" * 85)
        print(f"{'TOTAL STOCKS':<35} {'':>15} {'':>8} {'':>10} ₹{stock_total:>11,.2f}")

    # Sell decisions
    cursor.execute("SELECT COUNT(*) as cnt FROM sell_decisions")
    sell_count = cursor.fetchone()["cnt"]
    if sell_count:
        print(f"\nSell decisions tracked: {sell_count}")

    # Latest snapshot
    cursor.execute("""
        SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT 1
    """)
    snap = cursor.fetchone()
    if snap:
        print(f"\nLatest snapshot ({snap['date']}):")
        print(f"  Invested  : ₹{snap['total_invested']:>12,.2f}")
        print(f"  Current   : ₹{snap['total_current_value']:>12,.2f}")
        print(f"  P&L       : ₹{snap['total_pnl']:>12,.2f}")
        print(f"  Day Change: ₹{snap['day_change']:>12,.2f}")

    print(f"\n{'='*80}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Mutual Fund Decision Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py import-cas --pdf cas-report.xlsx
  python cli.py import-cas --pdf cas-statement.pdf --password mypassword
  python cli.py import-stocks --pdf cdsl_statement.pdf
  python cli.py download-cas
  python cli.py sell --scheme "HDFC Flexi Cap" --units 100 --price 45.5 --reason "Need cash"
  python cli.py fetch-nav
  python cli.py evaluate
  python cli.py status
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # import-cas
    p_import = subparsers.add_parser("import-cas", help="Import CAS PDF/Excel into database")
    p_import.add_argument("--pdf", help="Path to CAS PDF or Excel file")
    p_import.add_argument("--password", help="CAS PDF password (not needed for Excel)")
    p_import.set_defaults(func=cmd_import_cas)

    # import-stocks
    p_stocks = subparsers.add_parser("import-stocks", help="Import stocks from CDSL statement PDF")
    p_stocks.add_argument("--pdf", required=True, help="Path to CDSL monthly statement PDF")
    p_stocks.set_defaults(func=cmd_import_stocks)

    # download-cas
    p_download = subparsers.add_parser("download-cas", help="Download CAS from MFCentral")
    p_download.set_defaults(func=cmd_download_cas)

    # email-cas
    p_email = subparsers.add_parser("email-cas", help="Fetch CAS PDF from email inbox")
    p_email.add_argument("--days", type=int, default=7, help="Search last N days (default: 7)")
    p_email.set_defaults(func=cmd_email_cas)

    # request-cas
    p_request = subparsers.add_parser("request-cas", help="Request CAS from CAMS, then fetch from email")
    p_request.set_defaults(func=cmd_request_cas)

    # sell
    p_sell = subparsers.add_parser("sell", help="Log a sell/withdrawal decision")
    p_sell.add_argument("--scheme", required=True, help="Scheme name or AMFI code")
    p_sell.add_argument("--units", type=float, required=True, help="Units sold")
    p_sell.add_argument("--price", type=float, required=True, help="Sell NAV/price")
    p_sell.add_argument("--reason", default="", help="Reason for selling")
    p_sell.add_argument("--date", help="Sell date (YYYY-MM-DD), defaults to today")
    p_sell.set_defaults(func=cmd_sell)

    # fetch-nav
    p_fetch = subparsers.add_parser("fetch-nav", help="Fetch latest NAV for all holdings")
    p_fetch.set_defaults(func=cmd_fetch_nav)

    # evaluate
    p_eval = subparsers.add_parser("evaluate", help="Run decision evaluation engine")
    p_eval.set_defaults(func=cmd_evaluate)

    # status
    p_status = subparsers.add_parser("status", help="Print portfolio summary")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
