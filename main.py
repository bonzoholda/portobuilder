# main.py
from fastapi.middleware.wsgi import WSGIMiddleware
from dashboard import app as flask_app   # Flask app in dashboard.py
from dashboard.app import app as fastapi_app  # FastAPI app

# Mount Flask under FastAPI at /dashboard
fastapi_app.mount("/dashboard", WSGIMiddleware(flask_app))

# fastapi_app is now the ASGI entrypoint
