# Delete one collision dump and the model finetuned from it on the Duo S.
#
#   python3 -m duos_node.clear_collision                # collision_0 (the default name), asks first
#   python3 -m duos_node.clear_collision --dry-run      # only show what would go
#   python3 -m duos_node.clear_collision --yes          # no question
#   python3 -m duos_node.clear_collision --name collision_1 --keep-model
#
# Removes  <collision_root>/<name>/            (camera_images, tof_distance_array, latents.npy, ...)
#          <throwaway_models>/<name>_finetune.pt / .onnx
#          <throwaway_models>/selected_train_samples.json, train_summary*.csv, train_val_loss_per_epoch.csv
#          (side outputs of the last finetune, they describe that model)
# Keeps    the seed checkpoint, the prepared replay latents (original_dataset), crash_events.log.
# The next retrain finetunes the newest .pt left in <throwaway_models>, i.e. the seed again,
# and the next dump recreates <collision_root>/<name>/ from scratch.

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
TQ_DIR = APP_ROOT / "training_quantization"
SIDE_OUTPUTS = ("selected_train_samples.json", "train_val_loss_per_epoch.csv")
SIDE_OUTPUT_GLOBS = ("train_summary*.csv",)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _count(path: Path) -> int:
    return 1 if path.is_file() else sum(1 for p in path.rglob("*") if p.is_file())


def _fmt(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} kB"


def _node_running() -> list:
    """pids of duos_node.main processes other than this one (node and a training child share the cmdline)."""
    try:
        out = subprocess.run(["pgrep", "-f", "duos_node[.]main"], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    return [int(p) for p in out if int(p) != os.getpid()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="delete a collision dump and its finetuned model")
    ap.add_argument("--name", default="collision_0", help="collision name (the node's --collision_name)")
    ap.add_argument("--collision_root", default=str(TQ_DIR / "collision_dataset" / "train"))
    ap.add_argument("--throwaway_models_dir", default=str(TQ_DIR / "throwaway_models"))
    ap.add_argument("--keep-dump", action="store_true", help="keep the dumped frames, delete only the model")
    ap.add_argument("--keep-model", action="store_true", help="keep the model, delete only the dumped frames")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask")
    ap.add_argument("--force", action="store_true", help="proceed although a node / training is running")
    a = ap.parse_args(argv)

    root = Path(a.collision_root).resolve()
    models = Path(a.throwaway_models_dir).resolve()
    targets = []   # (label, path)
    if not a.keep_dump:
        d = root / a.name
        if d.exists():
            targets.append(("dump", d))
    if not a.keep_model:
        for ext in (".pt", ".onnx", ".onnx.tmp"):
            p = models / f"{a.name}_finetune{ext}"
            if p.exists():
                targets.append(("model", p))
        for n in SIDE_OUTPUTS:
            p = models / n
            if p.exists():
                targets.append(("finetune output", p))
        for g in SIDE_OUTPUT_GLOBS:
            for p in sorted(models.glob(g)):
                targets.append(("finetune output", p))

    print(f"collision '{a.name}'  dumps: {root}  models: {models}")
    if not targets:
        print("nothing to delete (no dump folder and no finetuned model with that name)")
        return 0
    total = 0
    for label, p in targets:
        s = _size(p); total += s
        extra = f", {_count(p)} files" if p.is_dir() else ""
        print(f"  {label:16s} {p}  ({_fmt(s)}{extra})")
    print(f"  total {_fmt(total)}")

    left = sorted(p for p in models.glob("*.pt") if p not in [t[1] for t in targets])
    if not a.keep_model:
        print(f"  next retrain starts from: {left[-1].name if left else 'NOTHING - no .pt would be left, aborting'}")
        if not left:
            return 2

    running = _node_running()
    if running and not a.force:
        print(f"a node (pid {', '.join(map(str, running))}) is running: stop it first (Ctrl-C), or pass --force. "
              f"A running training could be writing exactly these files.")
        return 3

    if a.dry_run:
        print("dry run, nothing deleted")
        return 0
    if not a.yes:
        try:
            ans = input("delete? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("aborted")
            return 1
    for label, p in targets:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"deleted {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
