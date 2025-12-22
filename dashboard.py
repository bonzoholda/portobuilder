from flask import Flask, render_template
import sqlite3
import time
import os


app = Flask(__name__)
# Simple and reliable for same-container setups
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "trader.db")


def query(sql, params=()):
    # DEBUG: This will print in your Railway logs so we can see the truth
    print(f"🔍 Dashboard attempting to read: {DB}")
    if not os.path.exists(DB):
        print("❌ DATABASE FILE NOT FOUND!")
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
    print(f"DEBUG: Dashboard is looking for DB at: {DB}") # Add this
    if os.path.exists(DB):
        print(f"DEBUG: File size is {os.path.getsize(DB)} bytes")
    
    balances = query("SELECT * FROM balances")
    # --- ADD THIS LINE ---
    print(f"DEBUG: Found {len(balances)} rows in balances table.")
    for b in balances:
        print(f"DEBUG: {b['asset']} = {b['amount']}")
    # ---------------------
    
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
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
