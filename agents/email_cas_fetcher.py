"""Fetch CAS PDF from email inbox (CAMS/KFintech mailback service).

CAMS sends CAS PDF to your registered email when requested.
This module checks your email inbox for the latest CAS PDF attachment
and downloads it for import.

Setup:
1. Request CAS from CAMS: https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement
2. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env
3. For Gmail: use an App Password (not your regular password)
   - Go to myaccount.google.com → Security → 2-Step Verification → App passwords
"""
import email
import imaplib
import os
import logging
from datetime import datetime, timedelta
from email.header import decode_header

from config import (
    EMAIL_IMAP_SERVER, EMAIL_ADDRESS, EMAIL_APP_PASSWORD,
    CAS_EMAIL_SENDER, CAS_PDF_PATH,
)

logger = logging.getLogger(__name__)


def fetch_cas_from_email(days_back: int = 7) -> str | None:
    """Search email inbox for latest CAS PDF from CAMS/KFintech.

    Args:
        days_back: How many days back to search for CAS emails.

    Returns:
        Path to downloaded PDF, or None if not found.
    """
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print("Email credentials not configured.")
        print("Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in your .env file.")
        print("\nFor Gmail, use an App Password:")
        print("  1. Go to myaccount.google.com → Security → 2-Step Verification")
        print("  2. Scroll to 'App passwords' and generate one")
        print("  3. Set EMAIL_APP_PASSWORD=<16-char-app-password> in .env")
        return None

    print(f"\nSearching email for CAS PDF (last {days_back} days)...")
    print(f"Server: {EMAIL_IMAP_SERVER}")
    print(f"Account: {EMAIL_ADDRESS[:4]}****{EMAIL_ADDRESS[EMAIL_ADDRESS.index('@'):]}")

    try:
        # Connect to IMAP server
        mail = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER)
        mail.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        mail.select("INBOX")

        # Search for CAS emails from CAMS/KFintech
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")

        # Search for emails from known CAS senders
        senders = [
            "donotreply@camsonline.com",
            "noreply@camsonline.com",
            "donotreply@kfintech.com",
            "noreply@kfintech.com",
            "donotreply@mfcentral.com",
        ]

        pdf_path = None
        for sender in senders:
            search_criteria = f'(FROM "{sender}" SINCE {since_date})'
            status, messages = mail.search(None, search_criteria)

            if status != "OK" or not messages[0]:
                continue

            # Get the latest email
            msg_ids = messages[0].split()
            latest_id = msg_ids[-1]  # Most recent

            status, msg_data = mail.fetch(latest_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            # Extract subject for logging
            subject = decode_header(msg["Subject"])[0]
            subject_text = subject[0]
            if isinstance(subject_text, bytes):
                subject_text = subject_text.decode(subject[1] or "utf-8")
            print(f"  Found email: {subject_text}")
            print(f"  From: {sender}")
            print(f"  Date: {msg['Date']}")

            # Look for PDF attachment
            for part in msg.walk():
                content_type = part.get_content_type()
                filename = part.get_filename()

                if filename and (filename.lower().endswith(".pdf") or
                                 content_type == "application/pdf"):
                    # Decode filename if needed
                    if isinstance(filename, bytes):
                        filename = filename.decode()

                    # Save PDF
                    target = os.path.abspath(CAS_PDF_PATH)
                    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)

                    with open(target, "wb") as f:
                        f.write(part.get_payload(decode=True))

                    print(f"  ✓ Saved CAS PDF: {target}")
                    pdf_path = target
                    break

            if pdf_path:
                break

        mail.logout()

        if not pdf_path:
            print("  No CAS PDF found in recent emails.")
            print("\n  To get a CAS emailed to you:")
            print("  1. Go to https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement")
            print("  2. Enter your email and PAN")
            print("  3. Select 'Detailed' statement")
            print("  4. Set password and submit")
            print("  5. Wait a few minutes, then run this command again")

        return pdf_path

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP login failed: {e}")
        print(f"\n✗ Email login failed: {e}")
        print("  Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env")
        return None
    except Exception as e:
        logger.error(f"Email fetch failed: {e}", exc_info=True)
        print(f"\n✗ Error: {e}")
        return None


def request_and_fetch_cas() -> str | None:
    """Request CAS from CAMS via their website, then fetch from email.

    Note: The CAMS website may have its own captcha. This function
    opens the browser for the user to submit the request, then
    polls email for the resulting PDF.
    """
    import webbrowser
    from config import CAMS_CAS_URL

    print("\n" + "=" * 60)
    print("CAMS CAS Email Request")
    print("=" * 60)
    print(f"\nOpening CAMS statement request page...")
    print(f"URL: {CAMS_CAS_URL}")
    print()
    print("Steps:")
    print("  1. Enter your registered email address")
    print("  2. Enter your PAN")
    print("  3. Select 'Detailed' statement type")
    print("  4. Set PDF password (same as MF_CAS_PASSWORD in .env)")
    print("  5. Complete captcha and submit")
    print()
    print("The CAS PDF will be emailed to you within a few minutes.")
    print("=" * 60)

    webbrowser.open(CAMS_CAS_URL)

    input("\nPress ENTER after you've submitted the CAS request...")
    print("\nWaiting 2 minutes for email delivery...")

    import time
    time.sleep(120)

    return fetch_cas_from_email(days_back=1)


if __name__ == "__main__":
    path = fetch_cas_from_email()
    if path:
        print(f"\nReady to import: py cli.py import-cas --pdf {path}")
