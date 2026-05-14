import os
from dotenv import load_dotenv

load_dotenv()

# MFCentral credentials
MF_PAN = os.getenv("MF_PAN", "")
MF_CAS_PASSWORD = os.getenv("MF_CAS_PASSWORD", "")

# Paths
CAS_PDF_PATH = os.getenv("CAS_PDF_PATH", "./cas-statement.pdf")
DB_PATH = os.getenv("DB_PATH", "./portfolio.db")

# Extra stock tickers (beyond what's in stock_holdings table)
STOCK_TICKERS = [
    t.strip() for t in os.getenv("STOCK_TICKERS", "").split(",") if t.strip()
]

# Decision evaluation thresholds (%)
NEUTRAL_THRESHOLD = 3.0
GOOD_SELL_ALERT_PCT = 5.0
MISSED_GAINS_ALERT_PCT = 10.0

# Evaluation milestones (days after sell)
EVAL_MILESTONES = [7, 30, 90, 180]

# Scheduler
DAILY_FETCH_TIME = "07:30"  # IST

# MFCentral URL
MFCENTRAL_LOGIN_URL = "https://www.mfcentral.com/investor/login"

# CAMS email-based CAS (for automated periodic import)
CAMS_CAS_URL = "https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement"
EMAIL_IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")  # Gmail App Password
CAS_EMAIL_SENDER = "donotreply@camsonline.com"
