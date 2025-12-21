import sqlite3
import time
import os

DB_FILE = "bot.db"
MAX_DAILY_LOSS = -1.5  # USDC


# -------------------------
# DB Init
# -------------------------

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER,
        side TEXT,
        symbol TEXT,
        amount REAL,
        price REAL,
        tx TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pnl (
        date TEXT PRIMARY KEY,
        daily_pnl REAL
    )
    """)

    conn.commit()
    conn.close()


# -------------------------
# Controls
# -------------------------

def can_trade(state):
    return state["daily_pnl"] > MAX_DAILY_LOSS


# -------------------------
# State helpers
# -------------------------

def load_state():
    today = time.strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT daily_pnl FROM pnl WHERE date=?", (today,))
    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO pnl (date, daily_pnl) VALUES (?, ?)",
            (today, 0.0)
        )
        daily_pnl = 0.0
    else:
        daily_pnl = row[0]

    conn.commit()
    conn.close()

    return {
        "date": today,
        "daily_pnl": daily_pnl
    }


def update_pnl(state, pnl_delta):
    state["daily_pnl"] += pnl_delta

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        "UPDATE pnl SET daily_pnl=? WHERE date=?",
        (state["daily_pnl"], state["date"])
    )

    conn.commit()
    conn.close()


# -------------------------
# Metadata
# -------------------------

def set_meta(state=None, **kwargs):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    for k, v in kwargs.items():
        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (k, str(v))
        )

    conn.commit()
    conn.close()


# -------------------------
# Trades
# -------------------------

def record_trade(side, symbol, amount, tx_hash, price=None):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO trades (ts, side, symbol, amount, price, tx)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        side,
        symbol,
        amount,
        price,
        tx_hash
    ))

    conn.commit()
    conn.close()
