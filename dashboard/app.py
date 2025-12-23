# dashboard/app.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
import json
from pathlib import Path

app = FastAPI()
templates = Jinja2Templates(directory="templates")

SNAPSHOT_FILE = Path("portfolio_snapshots.json")

@app.get("/api/portfolio/history")  # Use @app.get instead of @app.route
async def portfolio_history():
    if not SNAPSHOT_FILE.exists():
        return JSONResponse(content=[])

    data = json.loads(SNAPSHOT_FILE.read_text())

    result = [
        {
            "time": d["ts"],
            "equity": d["value"],
            "type": d["type"]
        }
        for d in data
    ]
    return JSONResponse(content=result)
