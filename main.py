# main.py
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import RedirectResponse

# Import Flask and FastAPI apps
from dashboard.dashboard import app as flask_app  # Flask app
from dashboard.app import app as fastapi_app      # FastAPI app

# Mount Flask under /dashboard
fastapi_app.mount("/dashboard", WSGIMiddleware(flask_app))

# Optional: redirect root to Flask dashboard
@fastapi_app.get("/")
def root():
    return RedirectResponse("/dashboard/")
