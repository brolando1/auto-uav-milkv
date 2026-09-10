#!/usr/bin/env bash
# (Re)start an HTTP proxy on the PC (venv proxy.py) and the reverse ssh tunnel that exposes it
# on the Duo S as http://127.0.0.1:8899, so apt/pip/curl on the board can reach the internet.
#   bash tools/duos_proxy.sh [user@host]
S="${TMPDIR:-/tmp}"
pkill -f "proxy --hostname 127.0.0.1 --port 8899" 2>/dev/null
pkill -f "ssh -f -N -o ExitOnForwardFailure=yes" 2>/dev/null
pkill -f "ssh -f -N -R 8899" 2>/dev/null
sleep 1
nohup /home/broland/Desktop/milkv-drone/venv/bin/proxy --hostname 127.0.0.1 --port 8899 --log-level WARNING > "$S/duos_proxy.log" 2>&1 &
sleep 2
curl -s -x http://127.0.0.1:8899 -o /dev/null -w "PC via proxy: HTTP %{http_code}\n" --max-time 8 http://deb.debian.org/
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -R 8899:127.0.0.1:8899 "${1:-debian@10.2.250.1}" && echo "tunnel up"
ssh "${1:-debian@10.2.250.1}" 'timeout 8 curl -s -x http://127.0.0.1:8899 -o /dev/null -w "board via proxy: HTTP %{http_code}\n" http://deb.debian.org/'
