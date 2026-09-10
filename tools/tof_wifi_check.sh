#!/usr/bin/env bash
# check of the ToF-over-CPX path. Run it while this PC is on the
# CRAZYFLIE wifi and the Crazyradio is plugged in. It captures the crazyflie
# console over the radio and counts CPX packets on the wifi socket at the same
#   bash tools/tof_wifi_check.sh [radio-uri]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URI="${1:-radio://0/120/2M/E7E7E7E706}"
PY="$ROOT/venv/bin/python3"
LOG="$ROOT/tof_check_$(date +%Y%m%d_%H%M%S).log"
cd "$ROOT"

{
  echo "=== tof_wifi_check $(date) uri=$URI"
  echo "--- wifi: $(iwgetid -r 2>/dev/null || echo unknown)"
  if ! ping -c 1 -W 2 192.168.4.1 >/dev/null 2>&1; then
    echo "!!! 192.168.4.1 not reachable - not on the CRAZYFLIE wifi? (continuing with radio only)"
    WIFI_OK=0
  else
    echo "--- AI-deck reachable"
    WIFI_OK=1
  fi

  echo; echo "=== console over radio (35 s) ==="
  "$PY" tools/cf_assert_dump.py --uri "$URI" --seconds 35 > "$LOG.console" 2>&1 &
  CONSOLE_PID=$!
  sleep 8   # let the radio link come up first

  if [ "$WIFI_OK" = 1 ]; then
    echo; echo "=== CPX probe on wifi (20 s) ==="
    "$PY" tools/cpx_probe.py --seconds 20 2>&1
  fi

  wait $CONSOLE_PID
  echo; echo "=== console output ==="
  cat "$LOG.console"
  rm -f "$LOG.console"
} 2>&1 | tee "$LOG"

echo
echo "saved to $LOG  - switch wifi back and paste this file"
