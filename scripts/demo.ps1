# Starts everything the demo needs, on Windows, and opens the chat and the gateway dashboard.
#
#   .\scripts\demo.ps1             real models: Ollama + gateway + chat backend
#   .\scripts\demo.ps1 -Simulated  no models: the gateway's simulated backend
#   .\scripts\demo.ps1 -LiveSim    also starts the gateway's simulated live mode on port 8001,
#                                  where its own scheduler (batching, prefix cache) is visible
#   .\scripts\demo.ps1 -Stop       stops what this script started
#
# Expects the gateway cloned beside this repository (..\Multi-Model-Inference-Gateway-Simulator).
# Logs go to .run\. See docs/DEMO.md for what to show once it is up.

param(
    [switch]$Simulated,
    [switch]$Stop,
    [switch]$LiveSim,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$gatewayRepo = Join-Path (Split-Path -Parent $repo) "Multi-Model-Inference-Gateway-Simulator"
$run = Join-Path $repo ".run"
$pidFile = Join-Path $run "pids.txt"
$gatewayPort = 8000
$chatPort = 8100
$liveSimPort = 8001

function Stop-Demo {
    if (Test-Path $pidFile) {
        foreach ($id in Get-Content $pidFile) {
            # taskkill /T also stops uvicorn's child processes.
            & taskkill /PID $id /T /F 2>$null | Out-Null
        }
        Remove-Item $pidFile
        Write-Host "Stopped the gateways and the chat backend (Ollama is left running; 'ollama stop <model>' unloads a model)."
    } else {
        Write-Host "Nothing to stop."
    }
}

function Wait-Url([string]$url, [string]$name, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "$name did not answer at $url within $seconds s. See the logs in $run."
}

function Test-Port([int]$port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if ($Stop) { Stop-Demo; return }

if (-not (Test-Path (Join-Path $gatewayRepo "src\gateway\app.py"))) {
    throw "The gateway is not at $gatewayRepo. Clone it beside this repository."
}
foreach ($port in $gatewayPort, $chatPort, $liveSimPort) {
    if ($port -eq $liveSimPort -and -not $LiveSim) { continue }
    if (Test-Port $port) { throw "Port $port is already in use. Run .\scripts\demo.ps1 -Stop, or free it." }
}
New-Item -ItemType Directory -Force $run | Out-Null
$started = @()

# 1. Ollama, for real models.
if (-not $Simulated) {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) { throw "Ollama is not installed. Install it, or use -Simulated." }
    $up = $true
    try { Invoke-WebRequest "http://127.0.0.1:11434/api/version" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch { $up = $false }
    if (-not $up) {
        Write-Host "Starting Ollama..."
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $run "ollama.log") -RedirectStandardError (Join-Path $run "ollama.err.log")
        Wait-Url "http://127.0.0.1:11434/api/version" "Ollama" 30
    }
    $have = (& ollama list) -join "`n"
    foreach ($model in "llama3.2:1b-instruct-q4_K_M", "llama3.2:3b", "llama3.1:8b") {
        if ($have -notmatch [regex]::Escape($model)) {
            throw "Ollama does not have $model. Run: ollama pull $model"
        }
    }
    # Load each model now, straight into Ollama (not through the gateway, so no tenant is
    # charged and no metric is recorded). Otherwise the first message to each tier spends
    # seconds loading the model. Ollama may still unload one if memory is short.
    Write-Host "Loading the three models into Ollama..."
    foreach ($model in "llama3.2:1b-instruct-q4_K_M", "llama3.2:3b", "llama3.1:8b") {
        $body = @{ model = $model; keep_alive = "30m" } | ConvertTo-Json
        Invoke-WebRequest "http://127.0.0.1:11434/api/generate" -Method Post -Body $body `
            -ContentType "application/json" -UseBasicParsing -TimeoutSec 180 | Out-Null
    }
}

# 2. The frontend, built once.
$dist = Join-Path $repo "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
    Write-Host "Building the chat page (first run only)..."
    Push-Location (Join-Path $repo "frontend")
    try {
        if (-not (Test-Path "node_modules")) { npm ci; if ($LASTEXITCODE) { throw "npm ci failed" } }
        npm run build; if ($LASTEXITCODE) { throw "npm run build failed" }
    } finally { Pop-Location }
}

# 3. The gateway.
Write-Host "Starting the gateway on port $gatewayPort ($(if ($Simulated) { 'simulated backend' } else { 'real models via Ollama' }))..."
# The gateway reads its backend config from the environment it inherits.
if ($Simulated) {
    Remove-Item Env:GATEWAY_BACKENDS -ErrorAction SilentlyContinue
} else {
    $env:GATEWAY_BACKENDS = Join-Path $repo "config\backends.ollama-chat.yaml"
}
$gateway = Start-Process uv -WorkingDirectory $gatewayRepo -PassThru -WindowStyle Hidden `
    -ArgumentList "run", "uvicorn", "gateway.app:create_default_app", "--factory", "--port", "$gatewayPort" `
    -RedirectStandardOutput (Join-Path $run "gateway.log") -RedirectStandardError (Join-Path $run "gateway.err.log")
$started += $gateway.Id
Set-Content $pidFile $started

# 4. The chat backend.
Write-Host "Starting the chat backend on port $chatPort..."
$chat = Start-Process uv -WorkingDirectory (Join-Path $repo "backend") -PassThru -WindowStyle Hidden `
    -ArgumentList "run", "uvicorn", "gateway_chat.app:create_default_app", "--factory", "--port", "$chatPort" `
    -RedirectStandardOutput (Join-Path $run "chat.log") -RedirectStandardError (Join-Path $run "chat.err.log")
$started += $chat.Id
Set-Content $pidFile $started

# 5. Optionally, the gateway's simulated live mode: no model, the gateway's own scheduler.
if ($LiveSim) {
    Write-Host "Starting the gateway's simulated live mode on port $liveSimPort..."
    $saved = $env:GATEWAY_BACKENDS
    Remove-Item Env:GATEWAY_BACKENDS -ErrorAction SilentlyContinue
    $env:GATEWAY_SIMULATED_LIVE = "1"; $env:GATEWAY_SIM_SPEED = "5"; $env:GATEWAY_SEED = "7"
    $sim = Start-Process uv -WorkingDirectory $gatewayRepo -PassThru -WindowStyle Hidden `
        -ArgumentList "run", "uvicorn", "gateway.app:create_default_app", "--factory", "--port", "$liveSimPort" `
        -RedirectStandardOutput (Join-Path $run "livesim.log") -RedirectStandardError (Join-Path $run "livesim.err.log")
    Remove-Item Env:GATEWAY_SIMULATED_LIVE, Env:GATEWAY_SIM_SPEED, Env:GATEWAY_SEED
    if ($saved) { $env:GATEWAY_BACKENDS = $saved }
    $started += $sim.Id
    Set-Content $pidFile $started
}

try {
    Wait-Url "http://127.0.0.1:$gatewayPort/healthz" "The gateway" 90
    if ($LiveSim) { Wait-Url "http://127.0.0.1:$liveSimPort/healthz" "Simulated live mode" 90 }
    Wait-Url "http://127.0.0.1:$chatPort/api/health" "The chat backend" 90
} catch {
    Stop-Demo
    throw
}

Write-Host ""
Write-Host "Ready."
Write-Host "  Chat:              http://127.0.0.1:$chatPort"
Write-Host "  Gateway dashboard: http://127.0.0.1:$gatewayPort/dashboard/"
Write-Host "  Stop with:         .\scripts\demo.ps1 -Stop"
if ($LiveSim) { Write-Host "  Simulated live:    http://127.0.0.1:$liveSimPort/dashboard/  (no model runs; simulated)" }
if ($Simulated) { Write-Host "  Simulated backend: replies are placeholder tokens; timings are simulated." }
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$chatPort"
    Start-Process "http://127.0.0.1:$gatewayPort/dashboard/"
    if ($LiveSim) { Start-Process "http://127.0.0.1:$liveSimPort/dashboard/" }
}
