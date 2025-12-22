from flask import Flask, render_template
import sqlite3
import time
import os


app = Flask(__name__)
# Create a robust path that works locally and on Railway
if os.path.exists("/app/data"): # Railway Volume mount point
    DB = "/app/data/trader.db"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB = os.path.join(BASE_DIR, "trader.db")


def query(sql, params=()):
    # Add check to see if DB exists to prevent crashing
    if not os.path.exists(DB):
        return []
    
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


@app.route("/")
def index():
    balances = query("SELECT * FROM balances")
    trades = query("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20")

    today = int(time.time()) - 86400
    
    # Use try/except or helper to handle empty DB gracefully
    try:
        daily_rows = query("SELECT SUM(amount_out - amount_in) as pnl FROM trades WHERE timestamp > ?", (today,))
        daily = daily_rows[0]["pnl"] if daily_rows and daily_rows[0]["pnl"] else 0

        total_rows = query("SELECT SUM(amount_out - amount_in) as pnl FROM trades")
        total = total_rows[0]["pnl"] if total_rows and total_rows[0]["pnl"] else 0
    except Exception:
        daily, total = 0, 0

    return render_template(
        "index.html",
        balances=balances,
        trades=trades,
        daily_pnl=round(float(daily), 4),
        total_pnl=round(float(total), 4)
    )


if __name__ == "__main__":
    # 3. Fix: Railway provides the PORT environment variable.
    # If it's not there, it defaults to 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
