<#
.SYNOPSIS
    One-click startup for Web RAG system
.DESCRIPTION
    Starts PostgreSQL, Redis, backend API, Celery worker, and frontend.
    Idempotent - skips already-running services.
.NOTES
    Version: 2.0
#>

#Requires -Version 5.1

# ==============================================================
# Configuration
# ==============================================================
$PROJECT_ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND_DIR  = Join-Path $PROJECT_ROOT "backend"
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "frontend"
$COMPOSE_FILE = Join-Path $PROJECT_ROOT "docker-compose.yml"

# Environment file detection
$ENV_FILE = Join-Path $BACKEND_DIR ".env"
$ENV_EXAMPLE = Join-Path $BACKEND_DIR ".env.example"

# Python path detection (prefer local venv, fallback to system)
$VENV_PYTHON  = Join-Path $BACKEND_DIR "venv/Scripts/python.exe"
$VENV_PIP     = Join-Path $BACKEND_DIR "venv/Scripts/pip.exe"
$VENV_ACTIVATE = Join-Path $BACKEND_DIR "venv/Scripts/Activate.ps1"

# Container names
$PG_CONTAINER   = "web_rag_postgres"
$REDIS_CONTAINER = "web_rag_redis"

# Ports
$BACKEND_PORT  = 8000
$FRONTEND_PORT = 3000
$PG_PORT       = 5432
$REDIS_PORT    = 6379

# ==============================================================
# Utility Functions
# ==============================================================
function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[ OK ] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERR ] $args" -ForegroundColor Red }
function Write-Step  { Write-Host "`n========================" -ForegroundColor Magenta; Write-Host "  $args" -ForegroundColor Magenta; Write-Host "========================" -ForegroundColor Magenta }
function Write-Skip  { Write-Host "[SKIP] $args" -ForegroundColor DarkGray }

function Test-PortOpen {
    param([int]$Port, [string]$HostName = "127.0.0.1")
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $wait = $async.AsyncWaitHandle.WaitOne(2000)
        if ($wait) {
            $client.EndConnect($async) | Out-Null
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    }
    catch { return $false }
}

function Wait-ForPort {
    param([int]$Port, [string]$ServiceName, [int]$TimeoutSeconds = 60)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        if (Test-PortOpen $Port) {
            Write-Ok "$ServiceName ready (port $Port)"
            return $true
        }
        Start-Sleep -Seconds 2
        $elapsed += 2
        Write-Info "Waiting for $ServiceName... (${elapsed}s)"
    }
    Write-Warn "$ServiceName timeout (${TimeoutSeconds}s)"
    return $false
}

function Find-Python {
    # Try venv first
    if (Test-Path $VENV_PYTHON) {
        Write-Info "Using venv Python: $VENV_PYTHON"
        return $VENV_PYTHON
    }

    # Common Python install locations, skip WindowsApps stub
    $candidates = @(
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "D:\develop\anaconda\python.exe"
    )

    # Try where.exe to find real Python (not WindowsApps)
    try {
        $whereResult = & where.exe python 2>&1 | Where-Object { $_ -notmatch "WindowsApps" }
        if ($whereResult) { $candidates = @($whereResult) + $candidates }
    }
    catch {}

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            try {
                $version = & $candidate --version 2>&1
                if ($version -match "Python 3\.(1[1-9]|3[0-9])") {
                    Write-Info "Found Python: $candidate ($version)"
                    return $candidate
                }
            }
            catch { continue }
        }
    }

    Write-Err "Python 3.11+ not found! Please install it."
    return $null
}

# ==============================================================
# Step 0: Pre-flight Check
# ==============================================================
Clear-Host
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Web RAG System - One-click Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Info "Project root: $PROJECT_ROOT"
Write-Info ""

# Check .env
if (-not (Test-Path $ENV_FILE)) {
    Write-Warn ".env not found, creating from .env.example..."
    if (Test-Path $ENV_EXAMPLE) {
        Copy-Item $ENV_EXAMPLE $ENV_FILE
        Write-Warn ".env created. Please edit LLM_API_KEY before running."
        $key = Read-Host "Press Enter to continue, or e to edit .env"
        if ($key -eq "e") { notepad $ENV_FILE }
    }
    else {
        Write-Err ".env.example not found either."
        exit 1
    }
}

# ==============================================================
# Step 1: Docker Services (PostgreSQL + Redis)
# ==============================================================
Write-Step "Step 1/5: Infrastructure (PostgreSQL + Redis)"

# Check Docker
$dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
if (-not $dockerVersion) {
    Write-Err "Docker Desktop is not running! Please start it first."
    $choice = Read-Host "Press Enter after starting Docker, or q to quit"
    if ($choice -eq "q") { exit 1 }
    $dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
    if (-not $dockerVersion) {
        Write-Err "Docker still unavailable. Exiting."
        exit 1
    }
}
Write-Ok "Docker Desktop ready (version $dockerVersion)"

# PostgreSQL
$pgRunning = docker ps --filter "name=$PG_CONTAINER" --filter "status=running" --format "{{.Names}}" 2>$null
if ($pgRunning -eq $PG_CONTAINER) {
    Write-Skip "PostgreSQL already running ($PG_CONTAINER)"
}
else {
    Write-Info "Starting PostgreSQL (pgvector)..."
    docker compose -f $COMPOSE_FILE up -d 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "PostgreSQL failed to start."
        exit 1
    }
    Wait-ForPort $PG_PORT "PostgreSQL" 30
}

# Redis
$redisRunning = docker ps --filter "name=$REDIS_CONTAINER" --filter "status=running" --format "{{.Names}}" 2>$null
if ($redisRunning -eq $REDIS_CONTAINER) {
    Write-Skip "Redis already running ($REDIS_CONTAINER)"
}
else {
    $redisExists = docker ps -a --filter "name=$REDIS_CONTAINER" --format "{{.Names}}" 2>$null
    if ($redisExists -eq $REDIS_CONTAINER) {
        Write-Info "Redis container exists but stopped, starting..."
        docker start $REDIS_CONTAINER 2>&1
    }
    else {
        Write-Info "Starting Redis..."
        docker run -d --name $REDIS_CONTAINER -p ${REDIS_PORT}:6379 redis:7 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Redis failed to start."
        exit 1
    }
    Wait-ForPort $REDIS_PORT "Redis" 15
}

# ==============================================================
# Step 2: Python Virtual Environment & Dependencies
# ==============================================================
Write-Step "Step 2/5: Python environment & dependencies"

$PYTHON = Find-Python
if (-not $PYTHON) { exit 1 }

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Info "Creating Python virtual environment..."
    $venvDir = Join-Path $BACKEND_DIR "venv"
    & $PYTHON -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to create venv."
        exit 1
    }
    Write-Ok "Virtual environment created"
}
else {
    Write-Skip "Virtual environment exists"
}

# Quick dependency check
$checkCmd = "import structlog; import fastapi; import sqlalchemy; print('deps OK')"
$depsCheck = & $VENV_PYTHON -c $checkCmd 2>&1
if ($depsCheck -ne "deps OK") {
    Write-Info "Installing Python dependencies (first time may take 3-5 min)..."
    & $VENV_PIP install -r (Join-Path $BACKEND_DIR "requirements.txt") 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Some dependencies may have failed. Check manually."
    }
    Write-Ok "Dependencies installed"
}
else {
    Write-Skip "Python dependencies already installed"
}

# ==============================================================
# Step 3: Database Migration
# ==============================================================
Write-Step "Step 3/5: Database schema check"

# Wait for PostgreSQL to be fully ready
$pgReady = $false
for ($i = 0; $i -lt 10; $i++) {
    $pgCheck = docker exec $PG_CONTAINER pg_isready -U postgres 2>$null
    if ($pgCheck -match "accepting connections") { $pgReady = $true; break }
    Start-Sleep -Seconds 2
}

if ($pgReady) {
    Write-Ok "PostgreSQL accepting connections"
    $alembicCfg = Join-Path $BACKEND_DIR "alembic.ini"
    if (Test-Path $alembicCfg) {
        Write-Info "Running Alembic migration..."
        & $VENV_PYTHON -m alembic upgrade head 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Alembic migration complete"
        }
        else {
            Write-Warn "Alembic migration failed. App will auto-create tables on startup."
        }
    }
    else {
        Write-Info "No Alembic config. Tables will be auto-created on startup."
    }
}
else {
    Write-Warn "PostgreSQL not ready. Skipping migration check (will retry on startup)."
}

# ==============================================================
# Step 4: Start Backend API + Celery Worker
# ==============================================================
Write-Step "Step 4/5: Starting backend services"

# Backend API
$backendRunning = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${BACKEND_PORT}/api/health" -TimeoutSec 3 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { $backendRunning = $true }
}
catch {}

if ($backendRunning) {
    Write-Skip "Backend API already running (http://127.0.0.1:${BACKEND_PORT})"
}
else {
    Write-Info "Starting backend API (http://127.0.0.1:${BACKEND_PORT})..."
    $backendCmd = "cd '$BACKEND_DIR'; . '$VENV_ACTIVATE'; uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT} --reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Normal

    # Wait for backend to be ready
    $backendReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${BACKEND_PORT}/api/health" -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $backendReady = $true; break }
        }
        catch {}
        Write-Info "Waiting for backend... (${i}s)"
    }
    if ($backendReady) { Write-Ok "Backend API ready" }
    else { Write-Warn "Backend may not be ready yet. Check http://127.0.0.1:${BACKEND_PORT}/api/health" }
}

# Celery Worker
Write-Info "Starting Celery Worker..."
$celeryCmd = "cd '$BACKEND_DIR'; . '$VENV_ACTIVATE'; celery -A app.workers.celery_app.celery_app worker --loglevel=info"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $celeryCmd -WindowStyle Normal
Start-Sleep -Seconds 3
Write-Ok "Celery Worker started (new window)"

# ==============================================================
# Step 5: Start Frontend
# ==============================================================
Write-Step "Step 5/5: Starting frontend"

$frontendPortOpen = Test-PortOpen $FRONTEND_PORT

if ($frontendPortOpen) {
    Write-Skip "Frontend already running (http://localhost:${FRONTEND_PORT})"
}
else {
    if (-not (Test-Path (Join-Path $FRONTEND_DIR "node_modules"))) {
        Write-Info "Installing frontend dependencies (npm install)..."
        Push-Location $FRONTEND_DIR
        npm install 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "npm install failed. Please install frontend dependencies manually."
        }
        Pop-Location
    }
    else {
        Write-Skip "Frontend dependencies already installed"
    }

    Write-Info "Starting frontend dev server (http://localhost:${FRONTEND_PORT})..."
    $frontendCmd = "cd '$FRONTEND_DIR'; npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -WindowStyle Normal
    Start-Sleep -Seconds 3

    if (Test-PortOpen $FRONTEND_PORT) { Write-Ok "Frontend started" }
    else { Write-Warn "Frontend may not be ready yet." }
}

# ==============================================================
# Summary
# ==============================================================
Write-Step "Startup complete! Service status"

$services = @(
    @{ Name = "PostgreSQL";       Port = $PG_PORT;    URL = "localhost:${PG_PORT}" },
    @{ Name = "Redis";            Port = $REDIS_PORT; URL = "localhost:${REDIS_PORT}" },
    @{ Name = "Backend API";      Port = $BACKEND_PORT;  URL = "http://localhost:${BACKEND_PORT}/docs" },
    @{ Name = "Frontend";         Port = $FRONTEND_PORT; URL = "http://localhost:${FRONTEND_PORT}" }
)

foreach ($svc in $services) {
    $open = Test-PortOpen $svc.Port
    $icon = if ($open) { "[OK]" } else { "--" }
    Write-Host "  $icon $($svc.Name) - $($svc.URL)" -ForegroundColor $(if ($open) { "Green" } else { "Red" })
}

Write-Host ""
Write-Host "  Celery Worker: running in a separate PowerShell window" -ForegroundColor Gray
Write-Host ""
Write-Host "=== Usage Tips ===" -ForegroundColor Cyan
Write-Host "  1. Open http://localhost:${FRONTEND_PORT} in browser"
Write-Host "  2. Register -> Login -> Create a knowledge base"
Write-Host "  3. Upload a document (watch Celery window for processing)"
Write-Host "  4. Once ready, ask questions in the chat page"
Write-Host "  5. Close windows to stop services, or run: docker compose down"
Write-Host ""
Write-Host "  API docs: http://localhost:${BACKEND_PORT}/docs" -ForegroundColor Yellow
Write-Host "  Health:   http://localhost:${BACKEND_PORT}/api/health" -ForegroundColor Yellow
Write-Host "  Readiness: http://localhost:${BACKEND_PORT}/api/ready" -ForegroundColor Yellow
Write-Host ""

# Keep script alive if run directly
if ($Host.Name -eq "ConsoleHost") {
    Write-Host "Press Ctrl+C to stop (or close this window)" -ForegroundColor DarkGray
    while ($true) { Start-Sleep -Seconds 10 }
}