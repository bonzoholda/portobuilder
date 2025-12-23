# main.py
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from dashboard import flask_app  # your existing Flask app
from dashboard.app import app as fastapi_app   # your FastAPI app

# Mount Flask inside FastAPI at /dashboard
fastapi_app.mount("/dashboard", WSGIMiddleware(flask_app))

# Now FastAPI runs as main ASGI server:
# /api/... -> FastAPI
# /dashboard/... -> Flask
