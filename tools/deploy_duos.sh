#!/usr/bin/env bash
# Copy milkv/ to the Milk-V Duo S and check what the board has.
#   bash tools/deploy_duos.sh [user@host] [remote_dir]
# Defaults: root@192.168.42.1 (USB-NCM link) and /root/milkv.
# Crash pngs/pdfs, caches and the local venv are not copied.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-root@192.168.42.1}"
REMOTE_DIR="${2:-/root/milkv}"

echo "== deploying $ROOT/milkv -> $TARGET:$REMOTE_DIR"
ssh -o ConnectTimeout=5 "$TARGET" "mkdir -p '$REMOTE_DIR'"
rsync -az --info=stats1 --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  --exclude 'crash_*_visual.png' --exclude 'crash_*_plot.pdf' \
  --exclude 'throwaway_models/' --exclude 'collision_dataset/' --exclude 'recorded_dataset/' \
  --exclude 'original_dataset/' --exclude 'dataset/' --exclude 'simulation_last.log' \
  --exclude 'stargate*/' --exclude 'data/' \
  "$ROOT/milkv/" "$TARGET:$REMOTE_DIR/"

echo; echo "== board check"
ssh "$TARGET" bash -s "$REMOTE_DIR" <<'REMOTE'
D="$1"
echo "arch:    $(uname -m)   os: $(. /etc/os-release 2>/dev/null; echo ${PRETTY_NAME:-?})"
echo "python:  $(python3 --version 2>&1)   cpus: $(nproc)   mem: $(free -m | awk '/Mem:/{print $2}') MB"
echo "disk:    $(df -h "$D" | awk 'NR==2{print $4" free on "$6}')"
for m in numpy cv2 torch tflite_runtime; do
  python3 - "$m" <<'PY' 2>/dev/null || echo "  $m: MISSING"
import importlib, sys
m = importlib.import_module(sys.argv[1]); print(f"  {sys.argv[1]}: {getattr(m, '__version__', 'ok')}")
PY
done
echo "wifi:    $(iwgetid -r 2>/dev/null || echo 'not associated')   ip on wlan: $(ip -4 -o addr show 2>/dev/null | awk '/wlan/{print $4}' | head -1)"
echo "seed ckpt dir: $(ls "$D/training_quantization/throwaway_models" 2>/dev/null | head -3 | tr '\n' ' ')"
echo "protocol test:"; cd "$D" && timeout 120 python3 -m duos_node.tests.test_protocol 2>&1 | tail -3
REMOTE
