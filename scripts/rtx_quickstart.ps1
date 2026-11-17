# One-shot setup on a Windows RTX 3090 machine (Docker Desktop with WSL2 GPU support).
#   git clone <repo>; cd <repo>; powershell -ExecutionPolicy Bypass -File scripts\rtx_quickstart.ps1
$ErrorActionPreference = "Stop"
Write-Host "== checks"
docker compose version | Out-Null
try { nvidia-smi --query-gpu=name,memory.total --format=csv } catch { Write-Warning "nvidia-smi not found" }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "== build + start (first run pulls gpt-oss:20b, qwen2.5:7b, nomic-embed-text: ~18 GB)"
docker compose up -d --build

Write-Host "== waiting for the app"
$ok = $false
for ($i = 0; $i -lt 360; $i++) {
  try { if ((Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).StatusCode -eq 200) { $ok = $true; break } } catch {}
  Start-Sleep -Seconds 5
}
if (-not $ok) { Write-Error "app not healthy yet: docker compose logs -f ollama-pull app" }

Write-Host "== smoke tests inside the image"
docker compose exec -T app python -m pytest -q

Write-Host "== warm up models"
docker compose exec -T ollama ollama run qwen2.5:7b "ok" | Out-Null
docker compose exec -T ollama ollama run gpt-oss:20b "ok" | Out-Null

Write-Host "Open http://localhost:8000"
Write-Host "Timed demo run:    docker compose exec app python -m app.cli run --brief evals/briefs/invoice_templates.json"
Write-Host "Recorded STOP run: docker compose exec app python -m app.cli run --brief evals/briefs/crowded_todo_app.json --decide STOP"
