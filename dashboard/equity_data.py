import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "trader.db")

def load_equity(limit=1000):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT timestamp, total_equity
        FROM portfolio_snapshots
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))

    rows = c.fetchall()
    conn.close()

    rows.reverse()

    return [
        {
            "time": datetime.fromtimestamp(ts).isoformat(),
            "equity": equity
        }
        for ts, equity in rows
    ]
