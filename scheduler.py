"""Local background scheduler for daily NAV fetching and evaluation."""
import argparse
import logging
import os
import sys
from datetime import datetime

# Fix Windows terminal encoding for Unicode output
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import schedule
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DAILY_FETCH_TIME
from db.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def daily_job():
    """Run the daily fetch + evaluation pipeline."""
    logger.info("Starting daily job...")
    try:
        from agents.price_fetcher import run_daily_fetch
        from agents.evaluator import run_evaluation

        run_daily_fetch()
        run_evaluation()
        logger.info("Daily job completed successfully.")
    except Exception as e:
        logger.error(f"Daily job failed: {e}", exc_info=True)


def weekly_cas_job():
    """Try to re-import CAS from MFCentral or email (detects new buys/sells)."""
    logger.info("Weekly CAS refresh — attempting MFCentral download...")
    try:
        from agents.cas_downloader import download_cas
        from agents.cas_parser import import_cas_file
        from config import MF_CAS_PASSWORD, MF_PAN

        if not MF_PAN or not MF_CAS_PASSWORD:
            logger.info("MFCentral credentials not configured — skipping.")
            return

        pdf_path = download_cas()
        if pdf_path:
            logger.info(f"Downloaded CAS: {pdf_path}")
            import_cas_file(pdf_path, MF_CAS_PASSWORD)
            return

    except Exception as e:
        logger.warning(f"MFCentral download failed: {e}")

    # Fallback: try email
    logger.info("Falling back to email CAS check...")
    try:
        from agents.email_cas_fetcher import fetch_cas_from_email
        from agents.cas_parser import import_cas_file
        from config import MF_CAS_PASSWORD, EMAIL_ADDRESS

        if not EMAIL_ADDRESS:
            logger.info("Email not configured — skipping CAS email check.")
            return

        pdf_path = fetch_cas_from_email(days_back=7)
        if pdf_path:
            logger.info(f"Found CAS PDF from email: {pdf_path}")
            import_cas_file(pdf_path, MF_CAS_PASSWORD)
        else:
            logger.info("No new CAS PDF found.")
    except Exception as e:
        logger.error(f"Email CAS fetch failed: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="MF Tracker Daily Scheduler")
    parser.add_argument("--once", action="store_true",
                        help="Run once immediately and exit")
    parser.add_argument("--time", default=DAILY_FETCH_TIME,
                        help=f"Time to run daily (HH:MM, default: {DAILY_FETCH_TIME})")
    args = parser.parse_args()

    init_db()

    if args.once:
        logger.info("Running once...")
        daily_job()
        return

    schedule.every().day.at(args.time).do(daily_job)
    schedule.every().monday.at("08:00").do(weekly_cas_job)  # Check email for CAS every Monday

    logger.info(f"Scheduler started.")
    logger.info(f"  Daily NAV fetch : every day at {args.time} IST")
    logger.info(f"  Weekly CAS check: every Monday at 08:00 IST")
    logger.info("Press Ctrl+C to stop.")
    logger.info(f"Next run: {schedule.next_run()}")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
