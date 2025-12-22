import sqlite3
import json
import time
import os

# Create a robust path that works locally and on Railway
if os.path.exists("/app/data"): # Railway Volume mount point
    DB = "/app/data/trader.db"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB = os.path.join(BASE_DIR, "trader.db")

DB_FILE = DB
STATE_FILE = "state.json"


# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_FILE)
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
            tx TEXT
        )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS balances (
        asset TEXT PRIMARY KEY,
        amount REAL
    )
    """)
    
    # ---- Meta table ----
    c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value REAL
        )
    """)

    conn.commit()
    conn.close()


def record_trade(pair, side, amount_in, amount_out, price, tx):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT INTO trades (
            timestamp, pair, side, amount_in, amount_out, price, tx
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()),
        pair,
        side,
        amount_in,
        amount_out,
        price,
        tx
    ))

    conn.commit()
    conn.close()

def set_balance(asset, amount):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    INSERT OR REPLACE INTO balances VALUES (?,?)
    """, (asset, amount))

    conn.commit()
    conn.close()

def set_meta(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT INTO meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))

    conn.commit()
    conn.close()


def get_meta(key, default=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = c.fetchone()

    conn.close()
    return row[0] if row else default


# ================= BOT STATE =================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
