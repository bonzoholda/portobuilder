from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from equity_data import load_equity

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "balances": [],
            "total_portfolio": 0,
            "daily_pnl": 0,
            "total_pnl": 0,
            "trades": []
        }
    )


@app.get("/equity", response_class=HTMLResponse)
def equity_page(request: Request):
    data = load_equity()
    return templates.TemplateResponse(
        "equity.html",
        {
            "request": request,
            "equity_data": data
        }
    )
