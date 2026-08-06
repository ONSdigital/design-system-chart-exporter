# pylint: disable=invalid-name
import os

import gunicorn

# Tell gunicorn to run our app
wsgi_app = "app.main:app"

# Use uvicorn's worker class to serve the ASGI app
worker_class = "uvicorn_worker.UvicornWorker"

# Bind to the default port, overridable via the WEB_PORT environment variable
bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '30300')}"

# Replace gunicorn's 'Server' HTTP header to avoid leaking info to attackers
gunicorn.SERVER = ""

# Restart gunicorn worker processes every 1200-1250 requests
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1200"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# Log to stdout
accesslog = "-"

# Time out after 25 seconds
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "25"))

# Load app pre-fork to save memory and worker startup time
preload_app = True
# pylint: enable=invalid-name
