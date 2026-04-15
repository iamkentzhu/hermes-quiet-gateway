#!/usr/bin/env bash
set -e

REPO="iamkentzhu/hermes-quiet-gateway"
PLUGIN_DIR="${HOME}/.hermes/plugins/quiet-gateway"
BASE_URL="https://raw.githubusercontent.com/${REPO}/main/quiet-gateway"

echo "Installing hermes-quiet-gateway..."

if [ ! -d "${HOME}/.hermes/plugins" ]; then
  echo "Error: ~/.hermes/plugins not found. Is Hermes installed?"
  exit 1
fi

mkdir -p "$PLUGIN_DIR"
curl -fsSL "${BASE_URL}/__init__.py" -o "${PLUGIN_DIR}/__init__.py"
curl -fsSL "${BASE_URL}/plugin.yaml"  -o "${PLUGIN_DIR}/plugin.yaml"

echo ""
echo "Installed to ${PLUGIN_DIR}"
echo "Run: hermes gateway restart"
