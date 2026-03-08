#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
#  WordWeaveWeb — Script d'installation et de lancement des tests
#  Usage : bash run_tests.sh
# ══════════════════════════════════════════════════════════════════

set -e  # Arrêt immédiat en cas d'erreur

VENV_DIR=".venv-tests"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        WordWeaveWeb — Tests Unitaires            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Vérifier que Python est disponible ──────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "[ERREUR] Python 3 est introuvable. Installez-le depuis https://python.org"
  exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "[OK] Python détecté : $PYTHON_VERSION"

# ── 2. Créer l'environnement virtuel si absent ─────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo "[...] Création de l'environnement virtuel dans $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
  echo "[OK] Environnement virtuel créé."
else
  echo "[OK] Environnement virtuel déjà présent."
fi

# ── 3. Activer l'environnement virtuel ────────────────────────────
source "$VENV_DIR/bin/activate"
echo "[OK] Environnement virtuel activé."

# ── 4. Installer les dépendances ──────────────────────────────────
echo "[...] Installation des dépendances de test..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements-test.txt
echo "[OK] Dépendances installées."

# ── 5. Lancer les tests ───────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Lancement des tests..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# DATABASE_URL est requis à l'import du module shared (mocké, pas de vraie DB)
export DATABASE_URL="postgresql+asyncpg://test:test@localhost/test"

python3 -m pytest tests/ -v --tb=short

echo ""
echo "[OK] Tests terminés."
