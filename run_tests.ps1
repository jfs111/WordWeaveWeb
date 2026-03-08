# ══════════════════════════════════════════════════════════════════
#  WordWeaveWeb — Script d'installation et de lancement des tests
#  Usage : .\run_tests.ps1
#
#  Si la politique d'exécution bloque le script, lancez d'abord :
#  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# ══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$VenvDir = ".venv-tests"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        WordWeaveWeb — Tests Unitaires            ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Vérifier que Python est disponible ─────────────────────────
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "[OK] Python détecté : $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "[ERREUR] Python 3 est introuvable. Installez-le depuis https://python.org" -ForegroundColor Red
    exit 1
}

# ── 2. Créer l'environnement virtuel si absent ────────────────────
if (-not (Test-Path $VenvDir)) {
    Write-Host "[...] Création de l'environnement virtuel dans $VenvDir ..."
    & $pythonCmd -m venv $VenvDir
    Write-Host "[OK] Environnement virtuel créé." -ForegroundColor Green
} else {
    Write-Host "[OK] Environnement virtuel déjà présent." -ForegroundColor Green
}

# ── 3. Activer l'environnement virtuel ────────────────────────────
$activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Host "[ERREUR] Script d'activation introuvable : $activateScript" -ForegroundColor Red
    exit 1
}
& $activateScript
Write-Host "[OK] Environnement virtuel activé." -ForegroundColor Green

# ── 4. Installer les dépendances ──────────────────────────────────
Write-Host "[...] Installation des dépendances de test..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements-test.txt
Write-Host "[OK] Dépendances installées." -ForegroundColor Green

# ── 5. Lancer les tests ───────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
Write-Host "  Lancement des tests..." -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
Write-Host ""

# DATABASE_URL est requis à l'import du module shared (mocké, pas de vraie DB)
$env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"

python -m pytest tests/ -v --tb=short

Write-Host ""
Write-Host "[OK] Tests terminés." -ForegroundColor Green
