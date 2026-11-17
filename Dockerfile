FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-models.txt ./
RUN pip install -r requirements.txt \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r requirements-models.txt

COPY . .
RUN mkdir -p /app/data /app/outputs

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# First start: fetch the local_transformers weights into the hf_cache volume (skipped when cached;
# a failed download does not block the app, the claim checker then fails closed per claim).
CMD ["sh", "-c", "python -m app.llm.local_transformers --prefetch || true; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
