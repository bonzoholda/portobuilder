# main.py
import os
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import RedirectResponse

# Import Flask and FastAPI apps
from dashboard.dashboard import app as flask_app  # Flask app inside dashboard/dashboard.py
from dashboard.app import app as fastapi_app      # FastAPI app inside dashboard/app.py

# Optional: ensure Flask templates & static work
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
flask_app.template_folder = os.path.join(BASE_DIR, "dashboard", "templates")
flask_app.static_folder = os.path.join(BASE_DIR, "dashboard", "static")

# Mount Flask under /dashboard
fastapi_app.mount("/dashboard", WSGIMiddleware(flask_app))

# Redirect root to Flask dashboard
@fastapi_app.get("/")
def root():
    return RedirectResponse("/dashboard/")
