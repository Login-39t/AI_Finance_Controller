# Start the TallyProof API on Windows/PowerShell.
#   ./run-api.ps1            # http://localhost:8000  (reload on)
#   ./run-api.ps1 -Port 8010
param([int]$Port = 8000)

$env:PYTHONPATH = "backend/src;packages/domain;packages/reconciliation;packages/ai_investigation"
& ./.venv/Scripts/python.exe -m uvicorn ledgergraph_api.main:app --reload --port $Port
