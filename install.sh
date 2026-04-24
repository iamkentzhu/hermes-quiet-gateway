#!/usr/bin/env bash
set -e

REPO="iamkentzhu/hermes-quiet-gateway"
PLUGIN_DIR="${HOME}/.hermes/plugins/quiet-gateway"
CONFIG_PATH="${HOME}/.hermes/config.yaml"
BASE_URL="https://raw.githubusercontent.com/${REPO}/main/quiet-gateway"

echo "Installing hermes-quiet-gateway..."

if [ ! -d "${HOME}/.hermes/plugins" ]; then
  echo "Error: ~/.hermes/plugins not found. Is Hermes installed?"
  exit 1
fi

mkdir -p "$PLUGIN_DIR"
curl -fsSL "${BASE_URL}/__init__.py" -o "${PLUGIN_DIR}/__init__.py"
curl -fsSL "${BASE_URL}/plugin.yaml"  -o "${PLUGIN_DIR}/plugin.yaml"

if [ -f "$CONFIG_PATH" ]; then
  python3 - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
text = path.read_text()

if "quiet-gateway" in text:
    print("quiet-gateway already present in ~/.hermes/config.yaml")
    raise SystemExit(0)

lines = text.splitlines()
plugins_idx = next((i for i, line in enumerate(lines) if line.strip() == "plugins:" and not line.startswith((" ", "\t"))), None)

if plugins_idx is None:
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(["plugins:", "  enabled:", "  - quiet-gateway"])
else:
    enabled_idx = None
    next_top = len(lines)
    for i in range(plugins_idx + 1, len(lines)):
        line = lines[i]
        if line and not line.startswith((" ", "\t")):
            next_top = i
            break
        if line.strip() == "enabled:":
            enabled_idx = i
            break

    if enabled_idx is None:
        lines[plugins_idx + 1:plugins_idx + 1] = ["  enabled:", "  - quiet-gateway"]
    else:
        insert_at = enabled_idx + 1
        while insert_at < next_top and lines[insert_at].startswith("  - "):
            insert_at += 1
        lines.insert(insert_at, "  - quiet-gateway")

path.write_text("\n".join(lines) + "\n")
print("Enabled quiet-gateway in ~/.hermes/config.yaml")
PY
else
  cat > "$CONFIG_PATH" <<'YAML'
plugins:
  enabled:
  - quiet-gateway
YAML
  echo "Created ~/.hermes/config.yaml and enabled quiet-gateway"
fi

echo ""
echo "Installed to ${PLUGIN_DIR}"
echo "Run: hermes gateway restart"
