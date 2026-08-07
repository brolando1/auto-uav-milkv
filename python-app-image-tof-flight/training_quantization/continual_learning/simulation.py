from __future__ import annotations

# Import side-effect: set 'safe' environment variables
try:
    from . import env_safety  # type: ignore  # noqa: F401
except Exception:
    try:
        import env_safety  # type: ignore  # noqa: F401
    except Exception:
        pass

import argparse
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PARENT = THIS_DIR.parent

if __package__ in (None, ""):
    if str(PARENT) not in sys.path:
        sys.path.insert(0, str(PARENT))

    from setup_from_config import setup, load_data_config, DataConfig
    from run_training import run_training
    from save_statistics import save_statistics
    from ..model.gate_classifier_PyTorch_model import GateClassifier
    from prepare_collision import prepare_collisions
    from prepare_training import prepare_training
    from prepare_original_data_for_training import prepare_original_dataset_from_config
else:
    # execution as a module: python -m training_quantization.continual_learning.simulation
    from .setup_from_config import setup, load_data_config, DataConfig
    from .run_training import run_training
    from .save_statistics import save_statistics
    from ..model.gate_classifier_PyTorch_model import GateClassifier
    from .prepare_collision import prepare_collisions
    from .prepare_training import prepare_training
    from .prepare_original_data_for_training import prepare_original_dataset_from_config


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Full simulation: setup (prepare_collision + prepare_training) + training + saving statistics."
        )
    )
    ap.add_argument(
        "--cfg",
        default=str(THIS_DIR / "config.json"),
        help="Path to the config.json file",
    )
    args = ap.parse_args()

    cfg_path = Path(args.cfg)
    if not cfg_path.exists():
        alt = THIS_DIR / cfg_path.name
        if alt.exists():
            cfg_path = alt
        else:
            raise FileNotFoundError(f"Config file not found: {cfg_path}")

    print("================================================================")
    print("[SIMULATION] Starting full simulation")
    print(f"  config.json = {cfg_path}")
    print("================================================================")

    # Read config a first time to understand if force the regeneration
    # of the original_dataset or reuse the one already ready on disk.
    static_cfg = load_data_config(cfg_path)
    print(f"[SIMULATION] force_prepare_original_dataset = {bool(static_cfg.force_prepare_original_dataset)}")

    prepare_original_dataset_from_config(
        cfg_path,
        GateClassifier,
        force=bool(static_cfg.force_prepare_original_dataset),
    )

    # 1) SETUP
    tt0 = time.perf_counter()
    data_config = setup(cfg_path, GateClassifier)
    tt1 = time.perf_counter()
    setup_time_s = float(tt1 - tt0)
    print("----------------------------------------------------------------")
    print(f"[SIMULATION] Total setup time  = {setup_time_s:.3f}s")
    print("----------------------------------------------------------------")

    # construction of the collisions part + training buffer
    prepare_collisions(data_config)

    tt0 = time.perf_counter()
    prepare_training(data_config)
    tt1 = time.perf_counter()
    setup_time_s = float(tt1 - tt0)
    print(f"training preparation time = {setup_time_s:.3f}s")

    # 2) TRAINING
    t0 = time.perf_counter()
    data_config = run_training(data_config, global_t0=t0)
    t1 = time.perf_counter()
    train_time_s = float(t1 - t0)

    data_config.train_time_s = train_time_s

    print("----------------------------------------------------------------")
    print(f"[SIMULATION] Total training time (run_training) = {train_time_s:.3f}s")
    print("----------------------------------------------------------------")

    # 3) SAVING STATISTICS + COLLISION EVALUATION
    save_statistics(data_config)

    print("================================================================")
    print("[SIMULATION] End of simulation.")
    print("================================================================")


if __name__ == "__main__":
    main()