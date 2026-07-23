param(
  [string]$ComposeFile = "docker-compose.local.yml",
  [string]$EnvFile = ".env.docker"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
  if (Test-Path ".env.docker.example") {
    Copy-Item ".env.docker.example" $EnvFile
    Write-Host "Creato $EnvFile da .env.docker.example"
  } else {
    throw "File .env.docker.example non trovato."
  }
}

Write-Host "Avvio servizi locali..."
docker compose -f $ComposeFile --env-file $EnvFile up -d --build

Write-Host "Attendo che Ollama risponda..."
$maxAttempts = 60
for ($i = 0; $i -lt $maxAttempts; $i++) {
  try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 2
    break
  } catch {
    Start-Sleep -Seconds 2
  }
  if ($i -eq $maxAttempts - 1) {
    throw "Ollama non raggiungibile su localhost:11434"
  }
}

Write-Host "Pull modelli Ollama..."
docker exec idra_ollama_local ollama pull mxbai-embed-large
$llmModel = (Get-Content $EnvFile | Where-Object { $_ -match '^OLLAMA_LLM_MODEL=' } | ForEach-Object { $_.Split('=')[1] })
if ([string]::IsNullOrWhiteSpace($llmModel)) {
  $llmModel = "enggpt-2-16b-a3b"
}
docker exec idra_ollama_local ollama pull $llmModel

Write-Host "Stack locale pronto. API: http://localhost:3000, Chroma: http://localhost:8000, Ollama: http://localhost:11434"
