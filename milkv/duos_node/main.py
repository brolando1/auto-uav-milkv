# Entry point for the Milk-V Duo S node:
#   AI-deck wifi socket (camera + ToF) -> pairing -> inference -> PC link
# plus the crash-dump / finetune / hot-swap machinery.
#
# Run from milkv/ :
#   python3 -m duos_node.main --ckpt training_quantization/throwaway_models/<model>.pt --finetune_on_dump

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# must be first, sets the BLAS/RVV env vars before numpy/torch load
import training_quantization.continual_learning.env_safety  # noqa: F401,E402

import argparse    # noqa: E402
import time        # noqa: E402
import threading   # noqa: E402

import cv2         # noqa: E402  (headless build is fine, only imdecode is used)
import numpy as np  # noqa: F401,E402

from training_quantization.continual_learning.runtime_utils import (  # noqa: E402
    preload_training_modules,
    robust_set_device,
    MedianProbabilityFilter,
    EMAProbabilityFilter,
)
from common import protocol                     # noqa: E402
from duos_node.cpx_link import CPXLink             # noqa: E402
from duos_node.pairing import Pairer               # noqa: E402
from duos_node.pc_link import PCLink               # noqa: E402
from duos_node.inference_service import ModelManager, InferenceService  # noqa: E402
from duos_node.retrain_orchestrator import RetrainOrchestrator          # noqa: E402


def parse_args():
    tq_dir = APP_ROOT / "training_quantization"
    cl_dir = tq_dir / "continual_learning"

    parser = argparse.ArgumentParser(description="Milk-V Duo S flight/inference/retraining node")
    parser.add_argument("-n", "--deck_ip", default="192.168.4.1", help="AI-deck IP")
    parser.add_argument("-p", "--deck_port", type=int, default=5000, help="AI-deck port")
    parser.add_argument("--listen_host", default="0.0.0.0", help="Bind address for the PC link")
    parser.add_argument("--listen_port", type=int, default=5800, help="Port for the PC link")

    parser.add_argument("--fly", action="store_true",
                        help="Run the flight controller (setpoints go to the PC radio bridge)")

    parser.add_argument("--ckpt", type=str, required=True, help="Path to GateClassifier checkpoint (.pt)")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--cam_preproc", type=str, default="crop", choices=["crop", "resize"])
    parser.add_argument("--thr", type=float, default=0.5)
    parser.add_argument("--median_k", type=int, default=11)
    parser.add_argument("--navigator_mode", choices=["always", "gated"], default="always",
                        help="always: run the navigator on every frame (constant frame rate), its yaw is handed to "
                             "the controller only in auto mode with a gate; gated: compute it only then")
    parser.add_argument("--navigator_every", type=int, default=2,
                        help="run the gate navigator on every n-th frame it is needed on (1 = every frame); "
                             "the frames in between reuse the last yaw rate")
    parser.add_argument("--ema_percent", type=float, default=100)

    parser.add_argument("--buffer_n", type=int, default=90, help="Ring buffer size for the collision dump")
    parser.add_argument("--collision_root", type=str, default=str(tq_dir / "collision_dataset" / "train"))
    parser.add_argument("--collision_name", type=str, default="collision_0")
    parser.add_argument("--collision_label", type=str, default="no_gate", choices=["no_gate", "gate"])
    parser.add_argument("--record_root", type=str, default=str(tq_dir / "recorded_dataset" / "train"))
    parser.add_argument("--record_name", type=str, default="live_recording")

    parser.add_argument("--finetune_on_dump", action="store_true")
    parser.add_argument("--sim_cfg", type=str, default=str(cl_dir / "config.json"))
    parser.add_argument("--train_log", type=str, default=str(APP_ROOT / "simulation_last.log"))
    parser.add_argument("--throwaway_models_dir", type=str, default=str(tq_dir / "throwaway_models"))
    parser.add_argument("--log_tail_lines", type=int, default=10)
    parser.add_argument("--classifier_backend", choices=["onnx", "torch"], default="onnx",
                        help="onnx: classifier inference with onnxruntime from the checkpoint's .onnx sibling "
                             "(exported at startup / by the finetune; ~3.5x faster on the Duo S); torch: plain torch")
    parser.add_argument("--train_launcher", choices=["fork", "subprocess"], default="fork",
                        help="fork: training child forked off this process with torch preloaded (fast on the Duo S); "
                             "subprocess: fresh interpreter per training (slow, always safe)")

    args, _ = parser.parse_known_args()

    if int(args.median_k) <= 0 or int(args.median_k) % 2 == 0:
        raise ValueError("--median_k must be an odd number >= 1")
    if float(args.ema_percent) <= 0.0 or float(args.ema_percent) > 100.0:
        raise ValueError("--ema_percent must be in the range (0, 100]")
    return args


def main():
    args = parse_args()

    device = robust_set_device(deterministic=args.deterministic)
    print(f"[INFO] Using device: {device}")

    ckpt_path = Path(args.ckpt).resolve()
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")

    # the node computes latents at the same tap the finetune trains from
    latent_tap = "post_comb1"
    try:
        import json
        with open(args.sim_cfg, "r", encoding="utf-8") as f:
            latent_tap = str(json.load(f).get("latent_tap", latent_tap))
    except Exception as e:
        print(f"[WARN] Could not read latent_tap from {args.sim_cfg} ({e}), using {latent_tap}")
    model_manager = ModelManager(ckpt_path, device, latent_tap=latent_tap, classifier_backend=args.classifier_backend)
    pred_filter = MedianProbabilityFilter(window_size=int(args.median_k))
    ema_filter = EMAProbabilityFilter(alpha=float(args.ema_percent) / 100.0)

    orchestrator = RetrainOrchestrator(
        app_root=APP_ROOT,
        model_manager=model_manager,
        pred_filter=pred_filter,
        ema_filter=ema_filter,
        buffer_n=args.buffer_n,
        collision_root=args.collision_root,
        collision_name=args.collision_name,
        collision_label=args.collision_label,
        record_root=args.record_root,
        record_name=args.record_name,
        finetune_on_dump=args.finetune_on_dump,
        sim_cfg=args.sim_cfg,
        train_log=args.train_log,
        throwaway_models_dir=args.throwaway_models_dir,
        log_tail_lines=args.log_tail_lines,
        train_launcher=args.train_launcher,
    )
    if args.finetune_on_dump and args.train_launcher == "fork":
        t0 = time.monotonic()
        preload_training_modules()
        print(f"[INFO] Training pipeline preloaded for the fork launcher ({time.monotonic() - t0:.1f}s)")

    pairer = Pairer()
    stop_event = threading.Event()
    service = None  # set below, needed inside on_command

    from duos_node.drone_control import KeyState, FlightData, TelemetryState, RemoteCommander
    key_state = KeyState()
    flight_data = FlightData()
    telemetry = TelemetryState()
    flight_status = {'state': 'no_drone' if not args.fly else 'waiting_radio', 'auto': False}

    def on_command(cmd):
        name = cmd.get("cmd")
        if name == "keys":
            key_state.update(cmd.get("pressed", []))
        elif name == "telemetry":
            telemetry.update(cmd)
        elif name in ("crash", "dump"):
            print(f"[CMD] {name} received")
            orchestrator.trigger_dump(source=name)
        elif name == "record_start":
            orchestrator.start_recording()
        elif name == "record_stop":
            orchestrator.stop_recording()
        elif name == "ping":
            if service is not None:
                service.echo_t_pc = cmd.get("t_pc")
        elif name == "debug_inputs":
            if service is not None:
                service.request_debug_inputs()
        elif name == "quit":
            print("[CMD] quit received")
            stop_event.set()
        else:
            print(f"[CMD] Unknown command: {cmd}")

    pc_link = PCLink(host=args.listen_host, port=args.listen_port, on_command=on_command)

    def on_jpeg(jpeg_bytes, seq):
        # relay to the PC first so the viewer doesn't depend on inference speed
        pc_link.publish(protocol.FRAME_JPEG, protocol.encode_jpeg(seq, time.monotonic(), jpeg_bytes))
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        t0 = time.perf_counter()
        decoded = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        if service is not None:
            service.timing.record("jpeg_decode", (time.perf_counter() - t0) * 1000.0)
        pairer.on_camera(decoded, jpeg_bytes, seq)

    def on_tof(package):
        dist_bytes, status_bytes = package['raw']
        pc_link.publish(
            protocol.FRAME_TOF,
            protocol.encode_tof(package['metadata']['seq'], time.monotonic(), dist_bytes, status_bytes),
        )
        pairer.set_tof(package)
        flight_data.set_tof(package)

    cpx = CPXLink(deck_ip=args.deck_ip, deck_port=args.deck_port, on_jpeg=on_jpeg, on_tof=on_tof)

    service = InferenceService(
        pairer=pairer,
        model_manager=model_manager,
        pred_filter=pred_filter,
        ema_filter=ema_filter,
        orchestrator=orchestrator,
        pc_link=pc_link,
        cpx_link=cpx,
        thr=args.thr,
        cam_preproc=args.cam_preproc,
        median_k=args.median_k,
        ema_percent=args.ema_percent,
        flight_data=flight_data,
        flight_status=flight_status,
        key_state=key_state,
        navigator_every=args.navigator_every,
        navigator_mode=args.navigator_mode,
    )

    pc_link.start()
    cpx.start()

    infer_thread = threading.Thread(name="InferenceThread", target=service.run, daemon=True)
    infer_thread.start()

    def wait_for_quit():
        while not stop_event.is_set():
            time.sleep(0.2)

    try:
        if args.fly:
            # Flight decisions run here; the setpoints go out to the PC radio
            # bridge, which owns the Crazyradio and the cflib connection
            from duos_node.drone_control import drone_flight_controller

            commander = RemoteCommander(pc_link)
            control_thread = threading.Thread(
                name="FlightControl",
                target=drone_flight_controller,
                args=(commander, telemetry, flight_data, key_state, orchestrator, flight_status, stop_event),
                daemon=True,
            )
            control_thread.start()
            wait_for_quit()
            control_thread.join(timeout=5.0)
        else:
            wait_for_quit()
    except KeyboardInterrupt:
        pass
    finally:
        print("[INFO] Shutting down...")
        stop_event.set()
        service.stop()
        cpx.stop()
        pc_link.stop()
        orchestrator.shutdown()
        infer_thread.join(timeout=2.0)
        print("[INFO] Exiting.")


if __name__ == "__main__":
    main()
