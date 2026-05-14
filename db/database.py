import sqlite3
import os
from config import DB_PATH


def get_connection():
    """Get SQLite connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT NOT NULL,
            amc TEXT,
            scheme_name TEXT NOT NULL,
            isin TEXT,
            amfi_code TEXT,
            rta_code TEXT,
            scheme_type TEXT,
            advisor TEXT,
            current_units REAL DEFAULT 0,
            latest_nav REAL,
            latest_value REAL,
            cost_value REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(folio, scheme_name)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holding_id INTEGER,
            folio TEXT NOT NULL,
            scheme_name TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            amount REAL DEFAULT 0,
            units REAL DEFAULT 0,
            nav REAL,
            balance REAL,
            tx_type TEXT,
            dividend_rate REAL,
            FOREIGN KEY (holding_id) REFERENCES holdings(id),
            UNIQUE(folio, scheme_name, date, amount, units, tx_type)
        );

        CREATE TABLE IF NOT EXISTS daily_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amfi_code TEXT NOT NULL,
            scheme_name TEXT,
            date TEXT NOT NULL,
            nav REAL NOT NULL,
            UNIQUE(amfi_code, date)
        );

        CREATE TABLE IF NOT EXISTS stock_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close_price REAL NOT NULL,
            volume INTEGER,
            UNIQUE(ticker, date)
        );

        CREATE TABLE IF NOT EXISTS sell_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holding_id INTEGER,
            scheme_name TEXT NOT NULL,
            amfi_code TEXT,
            sell_date TEXT NOT NULL,
            sell_units REAL NOT NULL,
            sell_nav REAL NOT NULL,
            sell_value REAL NOT NULL,
            reason TEXT,
            source TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (holding_id) REFERENCES holdings(id)
        );

        CREATE TABLE IF NOT EXISTS decision_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sell_decision_id INTEGER NOT NULL,
            eval_date TEXT NOT NULL,
            days_since_sell INTEGER NOT NULL,
            current_nav REAL NOT NULL,
            hypothetical_value REAL NOT NULL,
            actual_sell_value REAL NOT NULL,
            diff_pct REAL NOT NULL,
            verdict TEXT NOT NULL,
            FOREIGN KEY (sell_decision_id) REFERENCES sell_decisions(id),
            UNIQUE(sell_decision_id, days_since_sell)
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_invested REAL DEFAULT 0,
            total_current_value REAL DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            day_change REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS stock_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isin TEXT NOT NULL UNIQUE,
            security_name TEXT NOT NULL,
            ticker TEXT,
            quantity REAL NOT NULL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            invested_value REAL DEFAULT 0,
            latest_price REAL,
            latest_value REAL,
            free_balance REAL DEFAULT 0,
            dp_id TEXT,
            client_id TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_holding ON transactions(holding_id);
        CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(tx_type);
        CREATE INDEX IF NOT EXISTS idx_daily_prices_amfi ON daily_prices(amfi_code, date);
        CREATE INDEX IF NOT EXISTS idx_sell_decisions_amfi ON sell_decisions(amfi_code);
        CREATE INDEX IF NOT EXISTS idx_decision_evals_sell ON decision_evaluations(sell_decision_id);
        CREATE INDEX IF NOT EXISTS idx_stock_holdings_ticker ON stock_holdings(ticker);
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    init_db()
