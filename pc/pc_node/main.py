# PC ground station: viewer + keyboard. The drone is flown from the Milk-V,
# this side only shows what the Duo S streams and forwards key presses.
#
# Run from pc/ :
#   sudo -E <python> -m pc_node.main --keyboard --viewer --duos-ip <duo_ip>

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import threading
import argparse
import time

stop_event = threading.Event()
shared_state = {'p_gate': 0.0,
                'lock': threading.Lock(),
                'crash': 0}

# keys forwarded to the flight controller on the Duo S:
# manual flight + i=auto, k=kill, space=takeoff
FORWARDED_KEYS = ['w', 'a', 's', 'd', 'q', 'e', 'o', 'p', 'i', 'k', 'space']
KEY_SEND_PERIOD_S = 0.033


def keyboard_command_sender(link):
    # global hotkeys, needs sudo. Tracked through key events, not polled:
    # keyboard.is_pressed() does not know the key names on macOS
    import keyboard
    pressed = set()

    def on_key(event):
        if event.name not in FORWARDED_KEYS:
            return
        if event.event_type == 'down':
            pressed.add(event.name)
        else:
            pressed.discard(event.name)

    keyboard.hook(on_key)
    print(f"[KEYS] Forwarding {FORWARDED_KEYS} to the Duo S ({1.0 / KEY_SEND_PERIOD_S:.0f} Hz)")
    while not stop_event.is_set():
        link.send_command({'cmd': 'keys', 'pressed': sorted(pressed)}, quiet=True)
        time.sleep(KEY_SEND_PERIOD_S)


def run(args, unknown):
    from pc_node.link_client import DuoLink
    from pc_node.display_viewer import remote_viewer

    link = DuoLink(args.duos_ip, args.duos_port, shared_state=shared_state)
    link.start()
    if args.keyboard:
        t = threading.Thread(name="KeySender", target=keyboard_command_sender, args=(link,), daemon=True)
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Ground station for the Duo S flight node")
    parser.add_argument("--keyboard", action="store_true",
                        help="Forward the flight keys (space/i/wasd/qe/op/k) to the Duo S at 30 Hz (needs sudo)")
    parser.add_argument("--viewer", action="store_true",
                        help="Show the camera/ToF/p(gate) windows (viewer args: --plot, --show_model_inputs, ...)")
    parser.add_argument("--duos-ip", default="192.168.42.1",
                        help="IP of the Milk-V Duo S on the wired link")
    parser.add_argument("--duos-port", type=int, default=5800)
    args, unknown = parser.parse_known_args()
    run(args, unknown)
