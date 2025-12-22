import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "trader.db")

def plot_equity(limit=1000):
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

    if not rows:
        print("No portfolio snapshots found.")
        return

    rows.reverse()  # chronological order

    times = [datetime.fromtimestamp(r[0]) for r in rows]
    equity = [r[1] for r in rows]

    plt.figure(figsize=(11, 4))
    plt.plot(times, equity, label="Total Equity", linewidth=2)
    plt.xlabel("Time")
    plt.ylabel("USD")
    plt.title("Portfolio Equity Curve")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    plot_equity()
