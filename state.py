import sqlite3
import json
import time
import os

# ================= PATHS =================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "trader.db")
STATE_FILE = os.path.join(BASE_DIR, "state.json")


# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()

    # ---- Trades table ----
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            amount_in REAL NOT NULL,
            amount_out REAL NOT NULL,
            price REAL,
            tx TEXT,
            strategy_tag TEXT,
            equity_before REAL,
            equity_after REAL
        )
    """)

    # ---- Balances table ----
    c.execute("""
        CREATE TABLE IF NOT EXISTS balances (
            asset TEXT PRIMARY KEY,
            amount REAL,
            price REAL DEFAULT 0,
            entry_price REAL DEFAULT 0,
            tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0,
            ath REAL DEFAULT 0,
            updated_at INTEGER
        )
    """)

    # ---- Meta table ----
    c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value REAL
        )
    """)

    # ---- Portfolio snapshots (NEW, SAFE) ----
    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            total_equity REAL,
            usdc_balance REAL,
            invested_value REAL,
            unrealized_pnl REAL,
            realized_pnl REAL
        )
    """)

    conn.commit()
    conn.close()


# ================= TRADES =================

def record_trade(
    pair,
    side,
    amount_in,
    amount_out,
    price,
    tx,
    strategy_tag=None,
    equity_before=None,
    equity_after=None
):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()

    c.execute("""
        INSERT INTO trades (
            timestamp, pair, side,
            amount_in, amount_out,
            price, tx,
            strategy_tag,
            equity_before, equity_after
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        pair,
        side,
        amount_in,
        amount_out,
        price,
        tx,
        strategy_tag,
        equity_before,
        equity_after
    ))

    conn.commit()
    conn.close()


# ================= BALANCES =================

def set_balance(asset, amount, price=0, entry_price=0):
    now = int(time.time())
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()

    c.execute("""
        INSERT INTO balances (
            asset, amount, price, entry_price, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(asset) DO UPDATE SET
            amount=excluded.amount,
            price=excluded.price,
            entry_price=excluded.entry_price,
            updated_at=excluded.updated_at
    """, (asset, amount, price, entry_price, now))

    conn.commit()
    conn.close()


# ================= META =================

def set_meta(key, value):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()

    c.execute("""
        INSERT INTO meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))

    conn.commit()
    conn.close()


def get_meta(key, default=0):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()

    c.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = c.fetchone()

    conn.close()
    return row[0] if row else default


# ================= PORTFOLIO =================

def get_total_equity():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT COALESCE(SUM(amount * price), 0)
        FROM balances
    """)
    total = c.fetchone()[0]

    conn.close()
    return total


def snapshot_portfolio(realized_pnl=0):
    total = get_total_equity()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT COALESCE(SUM(amount * price), 0)
        FROM balances
        WHERE asset != 'USDC'
    """)
    invested = c.fetchone()[0]

    c.execute("""
        SELECT COALESCE(amount * price, 0)
        FROM balances
        WHERE asset = 'USDC'
    """)
    usdc = c.fetchone()
    usdc_val = usdc[0] if usdc else 0

    unrealized = total - usdc_val - realized_pnl

    c.execute("""
        INSERT INTO portfolio_snapshots (
            timestamp,
            total_equity,
            usdc_balance,
            invested_value,
            unrealized_pnl,
            realized_pnl
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        total,
        usdc_val,
        invested,
        unrealized,
        realized_pnl
    ))

    conn.commit()
    conn.close()


# ================= BOT STATE (JSON) =================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ================= PORTFOLIO META HELPERS =================

def get_portfolio_baseline():
    return get_meta("portfolio_baseline", 0)


def set_portfolio_baseline(value):
    set_meta("portfolio_baseline", value)


def get_portfolio_peak():
    return get_meta("portfolio_peak", 0)


def set_portfolio_peak(value):
    set_meta("portfolio_peak", value)


def get_daily_start_value():
    return get_meta("daily_start_value", 0)


def set_daily_start_value(value):
    set_meta("daily_start_value", value)


def get_last_growth_lock_ts():
    return get_meta("last_growth_lock_ts", 0)


def set_last_growth_lock_ts(ts):
    set_meta("last_growth_lock_ts", ts)
