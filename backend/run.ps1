$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $env:PORT) { $env:PORT = "8000" }
if (-not $env:HOST) { $env:HOST = "0.0.0.0" }

$VenvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
  . $VenvActivate
}

python -m uvicorn app.main:app --reload --host $env:HOST --port $env:PORT

