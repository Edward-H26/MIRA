web: gunicorn memoria.asgi:application --worker-class uvicorn.workers.UvicornWorker --workers 1 --worker-connections 1000 --timeout 0 --keep-alive 120 --max-requests 2000 --max-requests-jitter 100

