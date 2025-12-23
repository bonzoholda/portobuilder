# dashboard.py
from flask import Flask, render_template, jsonify
import sqlite3
import time
import os

# === Import WSGIMiddleware to mount FastAPI ===
from fastapi.middleware.wsgi import WSGIMiddleware
from dashboard.app import app as fastapi_app  # your FastAPI app

app = Flask(__name__)

# Simple and reliable for same-container setups
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "trader.db")

# --- Existing query function ---
def query(sql, params=()):
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

# --- Flask routes ---
@app.route("/")
def index():
    print(f"DEBUG: Dashboard is looking for DB at: {DB}")
    if os.path.exists(DB):
        print(f"DEBUG: File size is {os.path.getsize(DB)} bytes")
    
    balance_rows = query("SELECT * FROM balances")
    
    balances_with_usd = []
    total_portfolio_usd = 0.0
    
    for b in balance_rows:
        b_dict = dict(b)
        price = b_dict.get('price', 0) or 0
        amount = b_dict.get('amount', 0) or 0
        usd_value = amount * price
        total_portfolio_usd += usd_value
        b_dict['usd_value'] = usd_value
        balances_with_usd.append(b_dict)
    
    trades = query("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20")
    today = int(time.time()) - 86400
    
    try:
        daily_rows = query("SELECT SUM(amount_out - amount_in) as pnl FROM trades WHERE timestamp > ?", (today,))
        daily = daily_rows[0]["pnl"] if daily_rows and daily_rows[0]["pnl"] else 0
        total_rows = query("SELECT SUM(amount_out - amount_in) as pnl FROM trades")
        total = total_rows[0]["pnl"] if total_rows and total_rows[0]["pnl"] else 0
    except Exception:
        daily, total = 0, 0

    return render_template(
        "index.html",
        balances=balances_with_usd,
        total_portfolio=round(total_portfolio_usd, 2),
        trades=trades,
        daily_pnl=round(float(daily), 4),
        total_pnl=round(float(total), 4)
    )

@app.route('/logs')
def get_logs():
    log_file = 'bot_activity.log'
    if not os.path.exists(log_file):
        return {"logs": ["No logs yet..."]}
    
    with open(log_file, 'r') as f:
        lines = f.readlines()
        last_logs = [line.strip() for line in lines[-20:]]
        last_logs.reverse() 
    return {"logs": last_logs}

# === MOUNT FastAPI app under /api ===
app.wsgi_app = WSGIMiddleware(fastapi_app, app.wsgi_app)

# --- RUN ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
