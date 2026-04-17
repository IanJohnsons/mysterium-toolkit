#!/bin/bash
# Mysterium Node Toolkit — Version Bump Helper
# Usage: ./bump_version.sh [new_version]
# Example: ./bump_version.sh 1.0.0
#
# What it does:
#   1. Writes the new version to VERSION
#   2. Updates the shields.io badge in README.md
#   3. Confirms all changes

set -e

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TOOLKIT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Read current version ──────────────────────────────────────────────────────
CURRENT=$(cat VERSION 2>/dev/null || echo "unknown")

# ── Get new version from argument or prompt ───────────────────────────────────
if [ -n "$1" ]; then
    NEW="$1"
else
    echo -e "${BOLD}Current version: ${YELLOW}${CURRENT}${NC}"
    echo
    read -p "  New version (e.g. 1.0.0): " NEW
fi

if [ -z "$NEW" ]; then
    echo -e "${RED}✗ No version provided — aborting.${NC}"
    exit 1
fi

# Basic format check — must be X.Y.Z
if ! echo "$NEW" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo -e "${RED}✗ Invalid version format. Use X.Y.Z (e.g. 1.0.0)${NC}"
    exit 1
fi

echo
echo -e "  ${DIM}${CURRENT}${NC} → ${GREEN}${BOLD}${NEW}${NC}"
echo

# ── 1. Write VERSION file ─────────────────────────────────────────────────────
echo "$NEW" > VERSION
echo -e "  ${GREEN}✓${NC} VERSION → ${NEW}"

# ── 2. Update README.md badge ────────────────────────────────────────────────
README="$TOOLKIT_DIR/README.md"
if [ -f "$README" ]; then
    # Replace the version number inside the shields.io badge URL
    # Matches: https://img.shields.io/badge/version-X.Y.Z-brightgreen
    sed -i "s|img\.shields\.io/badge/version-[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*-brightgreen|img.shields.io/badge/version-${NEW}-brightgreen|g" "$README"
    echo -e "  ${GREEN}✓${NC} README.md badge → v${NEW}"
else
    echo -e "  ${YELLOW}⚠ README.md not found — skipped${NC}"
fi

# ── 3. Summary ────────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}✓ Version bumped to ${BOLD}v${NEW}${NC}"
echo
echo -e "  ${DIM}Next steps:${NC}"
echo -e "  ${DIM}  git add VERSION README.md${NC}"
echo -e "  ${DIM}  git commit -m \"chore: bump version to v${NEW}\"${NC}"
echo -e "  ${DIM}  git tag v${NEW}${NC}"
echo -e "  ${DIM}  git push && git push --tags${NC}"
echo
