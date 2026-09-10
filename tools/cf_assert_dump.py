# Capture the crazyflie console for a while and force the stored assert info
# (system.assertInfo=1) so we see "Assert failed at <file>:<line>" even if the
# board is crash-looping. No power cycle unless --reset is given.
#   python3 tools/cf_assert_dump.py [--uri radio://...] [--seconds 30] [--reset]
import argparse, sys, time
import cflib.crtp
from cflib.crazyflie import Crazyflie

ap = argparse.ArgumentParser()
ap.add_argument("--uri", default="radio://0/120/2M/E7E7E7E706")
ap.add_argument("--seconds", type=float, default=30.0)
ap.add_argument("--reset", action="store_true", help="power-cycle the STM32 first")
a = ap.parse_args()

cflib.crtp.init_drivers()
if a.reset:
    from cflib.utils.power_switch import PowerSwitch
    print("power-cycling STM32 ...")
    PowerSwitch(a.uri).stm_power_cycle()
    time.sleep(0.3)

cf = Crazyflie(rw_cache="pc/cache")
state = {"connected": False, "lines": [], "asked": False}

def on_console(text):
    state["lines"].append(text)
    sys.stdout.write(text); sys.stdout.flush()

def on_connected(uri):
    state["connected"] = True
    print(f"\n[connected {time.strftime('%H:%M:%S')}]")

def on_disconnected(uri):
    if state["connected"]:
        print(f"\n[disconnected {time.strftime('%H:%M:%S')}]  (board reset?)")
    state["connected"] = False
    state["asked"] = False

cf.console.receivedChar.add_callback(on_console)
cf.connected.add_callback(on_connected)
cf.disconnected.add_callback(on_disconnected)
cf.connection_failed.add_callback(lambda uri, msg: None)
cf.connection_lost.add_callback(lambda uri, msg: None)

t_end = time.time() + a.seconds
print("listening on", a.uri, "for", a.seconds, "s (reconnects automatically)")
while time.time() < t_end:
    if not state["connected"]:
        try:
            cf.open_link(a.uri)
        except Exception:
            pass
        for _ in range(30):
            time.sleep(0.1)
            if state["connected"]:
                break
        if not state["connected"]:
            try: cf.close_link()
            except Exception: pass
            continue
    if state["connected"] and not state["asked"]:
        time.sleep(2.0)
        try:
            cf.param.set_value("system.assertInfo", "1")
            state["asked"] = True
            print("[asked firmware to dump assert info]")
        except Exception as e:
            print("[param set failed:", e, "]")
    time.sleep(0.2)

try: cf.close_link()
except Exception: pass
txt = "".join(state["lines"])
print("\n--- summary ---")
for line in txt.splitlines():
    if any(k in line for k in ("Assert", "assert", "Hardfault", "resumed", "ToF", "SYS: Build")):
        print(" ", line)
