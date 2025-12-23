# main.py
from fastapi.middleware.wsgi import WSGIMiddleware
from dashboard import app as flask_app      # dashboard.py → Flask app
from app import app as fastapi_app          # app.py → FastAPI app

# Mount Flask under FastAPI
fastapi_app.mount("/dashboard", WSGIMiddleware(flask_app))
