from flask import Flask, render_template
import sqlite3
import time

app = Flask(__name__)
DB = "trader.db"


def query(sql, params=()):
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
    daily = query(
        "SELECT SUM(amount_out - amount_in) as pnl FROM trades WHERE timestamp > ?",
        (today,)
    )[0]["pnl"] or 0

    total = query(
        "SELECT SUM(amount_out - amount_in) as pnl FROM trades"
    )[0]["pnl"] or 0

    return render_template(
        "index.html",
        balances=balances,
        trades=trades,
        daily_pnl=round(daily, 4),
        total_pnl=round(total, 4)
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
