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
    print(f"DEBUG: Dashboard is looking for DB at: {DB}")
    if os.path.exists(DB):
        print(f"DEBUG: File size is {os.path.getsize(DB)} bytes")
    
    # Fetch raw balance rows
    balance_rows = query("SELECT * FROM balances")
    
    # --- NEW LOGIC: Calculate USD Values ---
    balances_with_usd = []
    total_portfolio_usd = 0.0
    
    for b in balance_rows:
        # Convert sqlite3.Row to dict to add new calculated fields
        b_dict = dict(b)
        
        # Ensure price exists in DB, default to 0 if column is missing
        price = b_dict.get('price', 0) or 0
        amount = b_dict.get('amount', 0) or 0
        
        usd_value = amount * price
        total_portfolio_usd += usd_value
        
        # Add the calculated value back to the dict for the HTML
        b_dict['usd_value'] = usd_value
        balances_with_usd.append(b_dict)
    
    print(f"DEBUG: Found {len(balances_with_usd)} balances. Total Portfolio: ${total_portfolio_usd}")
    # ---------------------------------------

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
        balances=balances_with_usd, # Use the new list with USD values
        total_portfolio=round(total_portfolio_usd, 2), # New variable for HTML
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
        # Read all lines and take the last 20
        lines = f.readlines()
        last_logs = [line.strip() for line in lines[-20:]]
        # Reverse them so the newest is on top
        last_logs.reverse() 
        
    return {"logs": last_logs}


if __name__ == "__main__":
    # 3. Fix: Railway provides the PORT environment variable.
    # If it's not there, it defaults to 5000.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
