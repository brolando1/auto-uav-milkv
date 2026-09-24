# PC ground station: viewer + keyboard + radio bridge. The Crazyradio is
# plugged in here, but all flight decisions come from the Milk-V as SETPOINT
# frames - this side just executes them (see radio_bridge.py) and forwards key
# presses + telemetry.
#
# Run from pc/ :
#   sudo -E <python> -m pc_node.main --fly --keyboard --viewer --duos-ip <duo_ip>

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import threading
import argparse
import time

console_buffer = ''
def console_callback(char):
    global console_buffer
    console_buffer += char
    print("[CF]", console_buffer, end="")
    console_buffer = ''

stop_event = threading.Event()
shared_state = {'p_gate': 0.0,
                'lock': threading.Lock(),
                'crash': 0}

# keys forwarded to the flight controller on the Duo S:
# manual flight + i=auto, k=kill, space=takeoff
FORWARDED_KEYS = ['w', 'a', 's', 'd', 'q', 'e', 'o', 'p', 'i', 'k', 'space']
KEY_SEND_PERIOD_S = 0.033


def keyboard_command_sender(link, bridge_holder):
    # global hotkeys, needs sudo
    import keyboard
    print(f"[KEYS] Forwarding {FORWARDED_KEYS} to the Duo S ({1.0 / KEY_SEND_PERIOD_S:.0f} Hz)")
    while not stop_event.is_set():
        pressed = [k for k in FORWARDED_KEYS if keyboard.is_pressed(k)]
        # hard kill straight on the local radio, works even if the Duo S hangs
        if 'k' in pressed and bridge_holder.get('bridge') is not None:
            bridge_holder['bridge'].kill_now()
        link.send_command({'cmd': 'keys', 'pressed': pressed}, quiet=True)
        time.sleep(KEY_SEND_PERIOD_S)


def run(args, unknown):
    from pc_node.link_client import DuoLink
    from pc_node.display_viewer import remote_viewer

    link = DuoLink(args.duos_ip, args.duos_port, shared_state=shared_state)
    bridge_holder = {'bridge': None}

    def ground_station():
        link.start()
        if args.keyboard:
            t = threading.Thread(name="KeySender", target=keyboard_command_sender,
                                 args=(link, bridge_holder), daemon=True)
            t.start()

        # The viewer runs inline on the MAIN thread: OpenCV's Qt backend binds
        # its event loop to the first thread that touches it and rejects GUI
        # calls from any other thread (blank windows / deadlocks).
        if args.viewer:
            sys.argv = [sys.argv[0]] + unknown
            try:
                remote_viewer(shared_state, link)   # blocks until 'z'
            finally:
                stop_event.set()
        else:
            try:
                while not stop_event.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                stop_event.set()

        link.stop()

    if args.fly:
        # Crazyradio is plugged in HERE; the Duo S streams the setpoints
        import cflib.crtp
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
        from pc_node.radio_bridge import RadioBridge

        cflib.crtp.init_drivers(enable_debug_driver=False)
        cf = Crazyflie(rw_cache=str(APP_ROOT / 'cache'))
        with SyncCrazyflie(args.uri, cf=cf) as scf:
            print(f"[INFO] Crazyflie connected on {args.uri}")
            scf.cf.console.receivedChar.add_callback(console_callback)
            bridge = RadioBridge(scf, link)
            link.on_setpoint = bridge.on_setpoint
            bridge_holder['bridge'] = bridge
            bridge.start()
            ground_station()
            bridge.stop()
    else:
        ground_station()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Ground station for the Duo S flight node")
    parser.add_argument("--fly", action="store_true",
                        help="Run the radio bridge: Crazyradio on this PC executes the Duo S setpoints")
    parser.add_argument("--keyboard", action="store_true",
                        help="Forward the flight keys (space/i/wasd/qe/op/k) to the Duo S at 30 Hz (needs sudo)")
    parser.add_argument("--viewer", action="store_true",
                        help="Show the camera/ToF/p(gate) windows (viewer args: --plot, --show_model_inputs, ...)")
    parser.add_argument("--duos-ip", default="192.168.42.1",
                        help="IP of the Milk-V Duo S on the wired link")
    parser.add_argument("--duos-port", type=int, default=5800)
    parser.add_argument("--uri", default="radio://0/120/2M/E7E7E7E7E7",
                        help="Crazyflie radio URI (used with --fly)")
    args, unknown = parser.parse_known_args()
    run(args, unknown)
