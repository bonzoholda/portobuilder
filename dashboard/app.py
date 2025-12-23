from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import json
from pathlib import Path


app = FastAPI()
templates = Jinja2Templates(directory="templates")


SNAPSHOT_FILE = Path("portfolio_snapshots.json")

@app.route("/api/portfolio/history")
def portfolio_history():
    if not SNAPSHOT_FILE.exists():
        return []

    data = json.loads(SNAPSHOT_FILE.read_text())

    return [
        {
            "time": d["ts"],
            "equity": d["value"],
            "type": d["type"]
        }
        for d in data
    ]
