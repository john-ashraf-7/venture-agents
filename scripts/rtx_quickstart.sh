#!/usr/bin/env bash
# One-shot setup on the RTX 3090 machine (Linux or WSL2 with Docker + NVIDIA Container Toolkit).
#   git clone <repo> && cd <repo> && bash scripts/rtx_quickstart.sh
set -euo pipefail

echo "== checks"
command -v docker >/dev/null || { echo "Docker is not installed"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 is required"; exit 1; }
if command -v nvidia-smi >/dev/null; then nvidia-smi --query-gpu=name,memory.total --format=csv; else echo "WARNING: nvidia-smi not found"; fi
docker run --rm --gpus all ubuntu:22.04 nvidia-smi -L >/dev/null 2>&1 && echo "GPU visible to Docker" \
  || echo "WARNING: Docker cannot see the GPU - install the NVIDIA Container Toolkit (or use docker-compose.cpu.yml)"

[ -f .env ] || cp .env.example .env

echo "== build + start (first run pulls gpt-oss:20b, qwen3:8b, nomic-embed-text: ~19 GB)"
docker compose up -d --build

echo "== waiting for the app"
for i in $(seq 1 360); do
  if curl -fs http://localhost:8000/health >/dev/null; then echo "app is up"; break; fi
  sleep 5
done
curl -fs http://localhost:8000/health || { echo "app not healthy yet: docker compose logs -f ollama-pull app"; exit 1; }

echo "== smoke tests inside the image (stubbed LLM, no GPU needed)"
docker compose exec -T app python -m pytest -q

echo "== warm up both models (first load is slow)"
docker compose exec -T ollama ollama run qwen3:8b "ok" >/dev/null 2>&1 || true
docker compose exec -T ollama ollama run gpt-oss:20b "ok" >/dev/null 2>&1 || true

echo
echo "Open http://localhost:8000"
echo "Timed demo run:   make demo        (or: docker compose exec app python -m app.cli run --brief evals/briefs/invoice_templates.json)"
echo "Recorded STOP run: make stop-run"
