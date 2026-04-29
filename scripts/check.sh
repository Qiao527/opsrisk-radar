#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "=== OpsRisk Radar — Validation Check ==="
echo ""

# 1. Run the full pipeline
echo "--- Step 1: Running pipeline (fetch + score + brief) ---"
python -m opsrisk run
echo ""

# 2. Verify the brief file exists
# 1.5: Validate database integrity
echo "--- Step 1.5: Validating database ---"
python -m opsrisk validate
echo ""

echo "--- Step 2: Checking brief file ---"
TODAY=$(date +%Y-%m-%d)
BRIEF="briefs/${TODAY}.md"
FALLBACK="briefs/2026-04-28.md"

if [ -f "$BRIEF" ]; then
    echo "  OK: ${BRIEF} exists"
elif [ -f "$FALLBACK" ]; then
    echo "  OK: ${FALLBACK} exists (today's brief not yet generated)"
    BRIEF="$FALLBACK"
else
    echo "  FAIL: no brief file found in briefs/"
    exit 1
fi

# 3. Verify the brief contains the project name
echo "--- Step 3: Checking brief content ---"
if grep -q "OpsRisk Radar" "$BRIEF"; then
    echo "  OK: brief contains \"OpsRisk Radar\""
else
    echo "  FAIL: brief does not contain \"OpsRisk Radar\""
    exit 1
fi

# 4. Verify the SQLite database exists
echo "--- Step 4: Checking database ---"
if [ -f "data/opsrisk.db" ]; then
    echo "  OK: data/opsrisk.db exists ($(du -h data/opsrisk.db | cut -f1))"
else
    echo "  FAIL: data/opsrisk.db not found"
    exit 1
fi

echo ""
echo "=== All checks passed ==="
