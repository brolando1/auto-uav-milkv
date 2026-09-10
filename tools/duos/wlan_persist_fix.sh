# Runs ON the Duo S as root: makes the drone-AP wifi config survive reboots (S30wifi rewrites the wlan0 stanza
# unless /boot/wpa_supplicant.conf exists) and reconnects wlan0.  scp it over, then: printf "rv\n" | sudo -S bash wlan_persist_fix.sh
set -e
SRC=/etc/wpa_supplicant/wpa_supplicant-wlan0.conf
# 1. the boot script (S30wifi) copies /boot/wpa_supplicant.conf -> /etc/wpa_supplicant.conf and then
#    does NOT rewrite interfaces.d/wlan0; without it it regenerates a PewPew-only stanza every boot
cp "$SRC" /boot/wpa_supplicant.conf
cp "$SRC" /etc/wpa_supplicant.conf
chmod 600 /etc/wpa_supplicant.conf
# 2. stanza that uses that file (drone AP priority 10, PewPew fallback priority 1)
cp /etc/network/interfaces.d/wlan0 /etc/network/wlan0.bak-regenerated-$(date +%Y%m%d-%H%M)
printf 'allow-hotplug wlan0\niface wlan0 inet dhcp\n\twpa-conf /etc/wpa_supplicant.conf\n' > /etc/network/interfaces.d/wlan0
echo "--- new stanza:"; cat /etc/network/interfaces.d/wlan0
# 3. restart wlan0 with it
ifdown wlan0 2>/dev/null || true
pkill -f "wpa_supplicant.*-i wlan0" || true
sleep 1
ifup wlan0
for i in $(seq 1 20); do
  st=$(wpa_cli -i wlan0 status 2>/dev/null | grep -E "^wpa_state" | cut -d= -f2)
  ip=$(ip -4 -o addr show wlan0 | awk '{print $4}')
  [ "$st" = "COMPLETED" ] && [ -n "$ip" ] && break
  sleep 1
done
echo "--- result after ${i}s:"; wpa_cli -i wlan0 status 2>/dev/null | grep -E "^(wpa_state|ssid|ip_address)"
ip -4 -br addr show wlan0
ping -c 2 -W 1 192.168.4.1 | tail -1
echo "--- default route (must NOT be via wlan0 / 192.168.4.1):"; ip route show default || echo "no default route"
