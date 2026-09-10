# Connect over the Crazyradio, print firmware revision + deck params, then
# power-cycle the STM32 and capture the console for ~15 s to see the app's
# DEBUG_PRINTs (they are lost unless a radio link is up when they are printed).
import sys, time
import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.utils.power_switch import PowerSwitch

uri = sys.argv[1] if len(sys.argv) > 1 else "radio://0/120/2M/E7E7E7E706"
cflib.crtp.init_drivers()
lines = []

def on_console(text):
    lines.append(text)
    sys.stdout.write(text); sys.stdout.flush()

def dump_info(scf):
    cf = scf.cf
    toc = cf.param.toc.toc
    for grp in ("firmware", "deck"):
        for name in sorted(toc.get(grp, {})):
            try:
                print(f"  {grp}.{name} = {cf.param.get_value(f'{grp}.{name}', timeout=3)}")
            except Exception as e:
                print(f"  {grp}.{name} = ? ({e})")

print("connecting to", uri)
try:
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="pc/cache")) as scf:
        print("connected. params:")
        dump_info(scf)
except Exception as e:
    print("first connect failed:", e)
    print("scanning ...", cflib.crtp.scan_interfaces())
    sys.exit(1)

print("\npower-cycling STM32 and reconnecting to catch the console ...")
PowerSwitch(uri).stm_power_cycle()
time.sleep(0.5)
with SyncCrazyflie(uri, cf=Crazyflie(rw_cache="pc/cache")) as scf:
    scf.cf.console.receivedChar.add_callback(on_console)
    print("connected, listening 15 s\n---console---")
    time.sleep(15)
print("\n---end---")
txt = "".join(lines)
for key in ("ToFDeck", "ERROR LOOP", "CPX", "AI-deck", "aideck", "ESP"):
    if key in txt:
        print(f"seen: {key}")
