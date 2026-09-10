# Standalone benchmark for the Duo S: what inference and retraining cost when the
# board does nothing else (no camera stream, no PC link, no relay threads).
#
#   cd ~/milkv && python3 -m duos_node.bench_standalone                 # 100 inference calls + 10 retrains
#   python3 -m duos_node.bench_standalone --retrain_runs 3 --torch      # fewer retrains, also time the torch classifier
#   python3 -m duos_node.bench_standalone --skip_retrain                # inference only
# Every single measurement is kept and written to --out_dir (default bench_results/ in the
# working directory): <stamp>.json (everything), <stamp>_inference.csv (one row per call),
# <stamp>_retrain.csv (one row per run).
#
# Inference: real frames from the last collision dump (the node's normalized 168x168
# camera / 21x21 ToF arrays) through the onnxruntime classifier and the navigator,
# plus jpeg decode + preprocessing on a camera-sized frame; mean / std / p95 per stage.
# Retraining: the real pipeline (simulation.main, forked like the node does it) on that
# dump, in a scratch copy of the model folder so the node's model chain is untouched;
# timed per run as setup (everything before the first epoch: fork, config, model and
# replay latents, dumped latents, training buffer), each epoch, checkpoint save, ONNX
# export and total (fork -> child exit), summarized over N runs.
# Refuses to run while a node is running (pass --force to override).

import argparse
import glob
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

APP_ROOT = Path(__file__).resolve().parents[1]
TQ_DIR = APP_ROOT / "training_quantization"
CL_DIR = TQ_DIR / "continual_learning"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import training_quantization.continual_learning.env_safety  # noqa: E402,F401  (thread limits like the node)


def _stats(v):
    v = [float(x) for x in v if x is not None]
    if not v:
        return "n/a"
    m = statistics.mean(v)
    sd = statistics.pstdev(v) if len(v) > 1 else 0.0
    s = sorted(v)
    p95 = s[int(0.95 * (len(s) - 1))]
    return f"{m:8.2f} ± {sd:5.2f}   min {s[0]:7.2f}   p95 {p95:7.2f}   max {s[-1]:7.2f}"


def _mem_mb():
    """current RSS and peak RSS (VmHWM) of this process in MB, from /proc."""
    rss = hwm = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) / 1024.0
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return rss, hwm


def _node_running():
    try:
        out = subprocess.run(["pgrep", "-f", "duos_node[.]main"], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    return [int(p) for p in out if int(p) != os.getpid()]


def _newest_pt(models_dir: Path):
    pts = sorted(models_dir.glob("*.pt"), key=lambda p: p.stat().st_mtime)
    return pts[-1] if pts else None


def _newest_dump(root: Path):
    leafs = [Path(p).parent for p in glob.glob(str(root / "*" / "*" / "camera_images"))]
    leafs = [d for d in leafs if list((d / "camera_images").glob("*.npy"))]
    if not leafs:
        return None
    return max(leafs, key=lambda d: d.stat().st_mtime)


def _load_dump(leaf: Path):
    cams = sorted((leaf / "camera_images").glob("*.npy"))
    tofs = sorted((leaf / "tof_distance_array").glob("*.npy"))
    n = min(len(cams), len(tofs))
    cam = np.stack([np.load(p).astype(np.float32) for p in cams[:n]])
    tof = np.stack([np.load(p).astype(np.float32) for p in tofs[:n]])
    return cam, tof


# ----------------------------------------------------------------------------- inference
def bench_inference(ckpt: Path, leaf: Path, calls: int, with_torch: bool):
    import cv2
    cv2.setNumThreads(0)
    from training_quantization.continual_learning.runtime_utils import (
        OnnxClassifier, onnx_sibling, onnx_is_fresh, load_gate_model, infer_gate_probability_with_latent,
    )
    from training_quantization.continual_learning.compat import export_classifier_onnx
    import training_quantization.continual_learning.img_preprocessing as img_preprocessing
    import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing
    from training_quantization.inference_gate_navigator_in_loop import InferenceGateNavigatorInLoop

    cam, tof = _load_dump(leaf)
    n = cam.shape[0]
    print(f"\n== inference: {calls} calls per stage over {n} dumped frames from {leaf} (plus one discarded first call)")
    rss_before, _ = _mem_mb()

    t0 = time.perf_counter()
    if not onnx_is_fresh(ckpt):
        import torch
        export_classifier_onnx(load_gate_model(str(ckpt), torch.device("cpu")), onnx_sibling(ckpt), "post_comb1")
    clf = OnnxClassifier(onnx_sibling(ckpt))
    t_clf_load = time.perf_counter() - t0
    t0 = time.perf_counter()
    nav = InferenceGateNavigatorInLoop()
    t_nav_load = time.perf_counter() - t0
    print(f"classifier: {onnx_sibling(ckpt).name} (session load {t_clf_load:.2f}s) | navigator backend: {nav.backend_name}, "
          f"opt {getattr(nav.backend, 'opt_level', '?')} (load {t_nav_load:.2f}s)")
    rss_loaded, _ = _mem_mb()

    # a camera-sized jpeg like the AI-deck sends (324x244 gray), built from a real frame:
    # undo the classifier normalization, paste the 168x168 crop on a mid-gray canvas
    mean_img, std_img = 0.2031, 0.0930
    crop_u8 = np.clip((cam[0] * std_img + mean_img) * 255.0, 0, 255).astype(np.uint8)
    canvas = np.full((244, 324), 128, np.uint8)
    canvas[(244 - 168) // 2:(244 - 168) // 2 + 168, (324 - 168) // 2:(324 - 168) // 2 + 168] = crop_u8
    ok, jpg = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    jpg = np.frombuffer(jpg.tobytes(), np.uint8)
    tof_mm = np.clip((tof[0][::3, ::3][:8, :8] * 0.6062 + 2.7159) * 1000.0, 0, 4000).astype(np.float32)

    # stages: jpeg_decode | crop_normalize (camera crop+normalize + ToF normalize) | classifier |
    #         navigator (input quantization + run) | both (classifier + navigator)
    keys = ["jpeg_decode", "crop_normalize", "classifier", "navigator", "both"]
    if with_torch:
        keys.append("classifier_torch")
    T = {k: [] for k in keys}
    frame_idx = []
    rss_calls, peak_calls = [], []   # RSS / peak RSS of the process after each call (MB)
    if with_torch:
        import torch
        torch.set_num_threads(1)
        model = load_gate_model(str(ckpt), torch.device("cpu"))
    for i in range(3):  # warm-up, not recorded
        clf.infer(cam[i % n], tof[i % n]); nav.set_sample_from_normalized(cam[i % n], tof[i % n]); nav.predict_navigation()
        cv2.imdecode(jpg, cv2.IMREAD_UNCHANGED)

    # one extra call at the start that is measured but discarded: the very first call
    # pays page-ins (visible as a 30-40 ms outlier in crop_normalize) that no later call pays
    def rec(key, ms):
        if c >= 0:
            T[key].append(ms)

    for c in range(-1, calls):
        i = c % n
        if c >= 0:
            frame_idx.append(i)
        t = time.perf_counter(); dec = cv2.imdecode(jpg, cv2.IMREAD_UNCHANGED); t1 = time.perf_counter()
        rec("jpeg_decode", (t1 - t) * 1e3)
        t = time.perf_counter()
        img_preprocessing.camera_norm_168(dec, preproc="crop")
        tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_mm)
        t1 = time.perf_counter()
        rec("crop_normalize", (t1 - t) * 1e3)

        t0c = time.perf_counter(); clf.infer(cam[i], tof[i]); t1 = time.perf_counter()
        rec("classifier", (t1 - t0c) * 1e3)
        t0n = time.perf_counter(); nav.set_sample_from_normalized(cam[i], tof[i]); nav.predict_navigation(); t3 = time.perf_counter()
        rec("navigator", (t3 - t0n) * 1e3)
        rec("both", (t1 - t0c) * 1e3 + (t3 - t0n) * 1e3)
        if with_torch:
            t = time.perf_counter()
            infer_gate_probability_with_latent(model, cam[i], tof[i], device=torch.device("cpu"), tap="post_comb1")
            rec("classifier_torch", (time.perf_counter() - t) * 1e3)

        if c >= 0:
            r_now, r_peak = _mem_mb()   # read outside the timed sections
            rss_calls.append(r_now); peak_calls.append(r_peak)

    print(f"{'stage (ms)':22s} {'mean ± std':>18s}")
    for k, v in T.items():
        print(f"  {k:20s} {_stats(v)}")
    clf_m, nav_m = statistics.mean(T["classifier"]), statistics.mean(T["navigator"])
    pre = statistics.mean(T["jpeg_decode"]) + statistics.mean(T["crop_normalize"])
    print(f"per-frame: classifier {clf_m:.1f} ms | navigator {nav_m:.1f} ms | both {clf_m + nav_m:.1f} ms | "
          f"decode + crop/normalize {pre:.1f} ms")
    print(f"idle-board frame budget: classifier only {pre + clf_m:.1f} ms ({1000 / (pre + clf_m):.1f} fps) | "
          f"navigator every 2nd frame {pre + clf_m + nav_m / 2:.1f} ms ({1000 / (pre + clf_m + nav_m / 2):.1f} fps) | "
          f"every frame {pre + clf_m + nav_m:.1f} ms ({1000 / (pre + clf_m + nav_m):.1f} fps)")
    rss_after, peak = _mem_mb()
    print(f"memory: RSS before loading the models {rss_before:.0f} MB (python + numpy + cv2 + onnxruntime + torch imported) | "
          f"after loading both models {rss_loaded:.0f} MB | after the calls {rss_after:.0f} MB | PEAK during inference {peak:.0f} MB")
    return {"stages_ms": T, "frame_index": frame_idx, "n_frames": n, "calls": calls,
            "rss_mb_per_call": rss_calls, "peak_rss_mb_per_call": peak_calls,
            "memory_mb": {"rss_before_models": rss_before, "rss_after_model_load": rss_loaded,
                          "rss_after_calls": rss_after, "peak_rss": peak,
                          "models_footprint": (rss_loaded - rss_before) if rss_loaded and rss_before else None},
            "classifier_onnx": onnx_sibling(ckpt).name, "classifier_session_load_s": t_clf_load,
            "navigator_backend": nav.backend_name, "navigator_opt_level": getattr(nav.backend, "opt_level", None),
            "navigator_load_s": t_nav_load}


# ----------------------------------------------------------------------------- retraining
def _child_run(cfg_path: Path, log_path: Path, timing_path: Path):
    """One retrain exactly like the node's forked child, with every stage timed."""
    import torch
    torch.set_num_threads(1)
    try:
        import cv2
        cv2.setNumThreads(0)
    except Exception:
        pass
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(fd, 1); os.dup2(fd, 2); os.close(fd)
    sys.stdout = os.fdopen(1, "w", buffering=1); sys.stderr = os.fdopen(2, "w", buffering=1)

    from training_quantization.continual_learning import simulation as sim
    timings = {}

    def timed(name):
        fn = getattr(sim, name)

        def w(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                timings[name] = time.perf_counter() - t
        return w

    for name in ("prepare_original_dataset_from_config", "setup", "prepare_collisions", "prepare_training",
                 "run_training", "save_statistics"):
        setattr(sim, name, timed(name))
    sys.argv = ["simulation", "--cfg", str(cfg_path)]
    t = time.perf_counter()
    sim.main()
    timings["main_total"] = time.perf_counter() - t
    timing_path.write_text(json.dumps(timings))


def _parse_log(log_path: Path):
    import re
    txt = log_path.read_text(errors="replace")
    g = lambda rx: (lambda m: float(m.group(1)) if m else None)(re.search(rx, txt))  # noqa: E731
    return {
        "epochs": [float(x) for x in re.findall(r"epoch \d+/\d+ \| time=([0-9.]+)s", txt)],
        "onnx_export": g(r"ONNX export: .*\(([0-9.]+)s\)"),
        "latents_reused": bool(re.search(r"using \d+ latents dumped by the node", txt)),
        "n_dump": g(r"using (\d+) latents dumped"),
        "items": g(r"total train items = (\d+)"),
    }


def bench_retrain(models_dir: Path, collision_root: Path, runs: int, keep_tmp: bool):
    print(f"\n== retraining: {runs} runs of the real pipeline on {collision_root} (scratch copy of {models_dir})")
    t = time.perf_counter()
    import torch  # noqa: F401
    from training_quantization.continual_learning.runtime_utils import preload_training_modules
    preload_training_modules()
    preload_s = time.perf_counter() - t
    print(f"one-time preload (torch, pipeline modules, Adam + ONNX exporter warm-up): {preload_s:.1f}s "
          f"(the node pays this once at startup)")

    tmp = Path(tempfile.mkdtemp(prefix="bench_retrain_", dir=str(TQ_DIR)))
    tmp_models = tmp / "throwaway_models"
    tmp_models.mkdir()
    for p in list(models_dir.glob("*.pt")) + list(models_dir.glob("*.onnx")):
        shutil.copy2(p, tmp_models / p.name)
    cfg = json.loads((CL_DIR / "config.json").read_text())
    for k in ("classification_root", "classification_fixed_root", "validation_root"):
        if cfg.get(k):
            cfg[k] = str((CL_DIR / cfg[k]).resolve())
    cfg["original_dataset_root"] = str((CL_DIR / "original_dataset").resolve())
    cfg["dataset_training_root"] = str(collision_root.resolve())
    cfg["model_original"] = str(tmp_models)
    cfg["outdir"] = str(tmp_models)
    cfg["force_prepare_original_dataset"] = False
    cfg_path = tmp / "config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    print(f"scratch dir: {tmp}  (epochs {cfg.get('epochs')}, batch {cfg.get('batch_size')}, tap {cfg.get('latent_tap')}, "
          f"replay gate/no_gate {cfg.get('n_original_gate_to_select')}/{cfg.get('n_original_no_gate_to_select')})")

    rows = []
    for r in range(runs):
        log_path = tmp / f"run_{r:02d}.log"
        timing_path = tmp / f"run_{r:02d}.json"
        t_fork = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            try:
                _child_run(cfg_path, log_path, timing_path)
                os._exit(0)
            except BaseException as e:  # noqa: BLE001
                try:
                    print(f"[bench child] failed: {e!r}")
                except Exception:
                    pass
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        wall = time.perf_counter() - t_fork
        rc = os.waitstatus_to_exitcode(status)
        peak_child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        if rc != 0 or not timing_path.exists():
            print(f"run {r + 1}: child failed (rc {rc}), see {log_path}")
            print(log_path.read_text(errors="replace")[-1500:])
            break
        tm = json.loads(timing_path.read_text())
        lg = _parse_log(log_path)
        onnx_t = lg["onnx_export"] or 0.0
        ckpt_t = tm.get("save_statistics", 0.0) - onnx_t
        epochs = lg["epochs"]
        # setup = everything that is not an epoch, the checkpoint save or the ONNX export:
        # fork, config, model + replay latents, dumped latents, training buffer, exit
        setup_t = wall - sum(epochs) - ckpt_t - onnx_t
        row = {"total": wall, "setup": setup_t, "epochs": epochs, "ckpt_save": ckpt_t, "onnx_export": onnx_t,
               "peak_child_mb": peak_child, "latents_reused": lg["latents_reused"], "n_dump": lg["n_dump"], "items": lg["items"]}
        rows.append(row)
        ep = "+".join(f"{e:.2f}" for e in epochs)
        print(f"run {r + 1:2d}: total {wall:6.2f}s = setup {setup_t:.2f} + epochs {ep} + ckpt {ckpt_t:.2f} + onnx {onnx_t:.2f} "
              f"| latents reused {row['latents_reused']} ({int(row['n_dump'] or 0)} dumped, {int(row['items'] or 0)} items) "
              f"| child peak RSS {peak_child:.0f} MB")

    if rows:
        print(f"\n== retraining statistics over {len(rows)} runs (seconds)")
        print(f"{'stage':32s} {'mean ± std':>18s}")
        print(f"  {'setup (everything before epoch 1)':30s} {_stats([r['setup'] for r in rows])}")
        n_ep = max(len(r["epochs"]) for r in rows)
        for i in range(n_ep):
            print(f"  {'epoch %d' % (i + 1):30s} {_stats([r['epochs'][i] for r in rows if len(r['epochs']) > i])}")
        print(f"  {'checkpoint save':30s} {_stats([r['ckpt_save'] for r in rows])}")
        print(f"  {'ONNX export':30s} {_stats([r['onnx_export'] for r in rows])}")
        print(f"  {'TOTAL (fork -> child exit)':30s} {_stats([r['total'] for r in rows])}")
        print(f"training child peak RSS: {max(r['peak_child_mb'] for r in rows):.0f} MB | latents reused in all runs: "
              f"{all(r['latents_reused'] for r in rows)} | dumped frames {int(rows[0]['n_dump'] or 0)}, "
              f"train items {int(rows[0]['items'] or 0)}")
        print("(in the node add ~0.7 s for writing the dump before the fork and ~2 s for noticing the child and hot-swapping)")
    if keep_tmp:
        print(f"scratch kept: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"runs": rows, "preload_s": preload_s, "config": {k: cfg.get(k) for k in
            ("epochs", "batch_size", "latent_tap", "n_original_gate_to_select", "n_original_no_gate_to_select", "lr")}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="idle-board benchmark: inference stages and retraining stages")
    ap.add_argument("--ckpt", default=None, help="checkpoint (.pt) to benchmark; default: newest in throwaway_models")
    ap.add_argument("--throwaway_models_dir", default=str(TQ_DIR / "throwaway_models"))
    ap.add_argument("--collision_root", default=str(TQ_DIR / "collision_dataset" / "train"))
    ap.add_argument("--dump", default=None, help="dump leaf dir with camera_images/; default: newest under collision_root")
    ap.add_argument("--inference_calls", type=int, default=100, help="measurements per inference stage")
    ap.add_argument("--out_dir", default="bench_results", help="where the json/csv with all measurements go")
    ap.add_argument("--retrain_runs", type=int, default=10)
    ap.add_argument("--torch", action="store_true", help="also time the torch classifier path")
    ap.add_argument("--skip_inference", action="store_true")
    ap.add_argument("--skip_retrain", action="store_true")
    ap.add_argument("--keep_tmp", action="store_true")
    ap.add_argument("--force", action="store_true", help="run although a node is running (numbers will be worse)")
    a = ap.parse_args(argv)

    running = _node_running()
    if running and not a.force:
        print(f"a node is running (pid {running}); stop it first so the board does nothing else, or pass --force")
        return 3

    models_dir = Path(a.throwaway_models_dir).resolve()
    ckpt = Path(a.ckpt).resolve() if a.ckpt else _newest_pt(models_dir)
    if ckpt is None or not ckpt.exists():
        print(f"no checkpoint found in {models_dir}")
        return 2
    leaf = Path(a.dump).resolve() if a.dump else _newest_dump(Path(a.collision_root))
    if leaf is None:
        print(f"no collision dump with frames under {a.collision_root}: fly/dump once first")
        return 2

    print(f"host: {os.uname().nodename} | python {sys.version.split()[0]} | checkpoint {ckpt.name} | dump {leaf}")
    result = {"host": os.uname().nodename, "python": sys.version.split()[0], "started": time.strftime("%Y-%m-%d %H:%M:%S"),
              "checkpoint": str(ckpt), "dump": str(leaf), "args": vars(a)}
    if not a.skip_inference:
        result["inference"] = bench_inference(ckpt, leaf, a.inference_calls, a.torch)
    if not a.skip_retrain:
        result["retrain"] = bench_retrain(models_dir, Path(a.collision_root), a.retrain_runs, a.keep_tmp)
    _write_results(Path(a.out_dir), result)
    return 0


def _write_results(out_dir: Path, result: dict):
    import csv
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    js = out_dir / f"bench_{stamp}.json"
    js.write_text(json.dumps(result, indent=1))
    written = [js]
    inf = result.get("inference")
    if inf:
        p = out_dir / f"bench_{stamp}_inference.csv"
        keys = list(inf["stages_ms"].keys())
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["call", "frame"] + [f"{k}_ms" for k in keys] + ["rss_mb"])
            for c in range(inf["calls"]):
                w.writerow([c, inf["frame_index"][c]] + [f"{inf['stages_ms'][k][c]:.3f}" for k in keys]
                           + [f"{inf['rss_mb_per_call'][c]:.1f}"])
        written.append(p)
    rt = result.get("retrain")
    if rt and rt["runs"]:
        p = out_dir / f"bench_{stamp}_retrain.csv"
        n_ep = max(len(r["epochs"]) for r in rt["runs"])
        cols = ["run", "setup_s"] + [f"epoch_{i + 1}_s" for i in range(n_ep)] + \
               ["ckpt_save_s", "onnx_export_s", "total_s", "peak_child_mb", "latents_reused", "n_dump", "items"]
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for i, r in enumerate(rt["runs"]):
                ep = [f"{r['epochs'][k]:.3f}" if k < len(r["epochs"]) else "" for k in range(n_ep)]
                w.writerow([i + 1, f"{r['setup']:.3f}"] + ep +
                           [f"{r['ckpt_save']:.3f}", f"{r['onnx_export']:.3f}", f"{r['total']:.3f}",
                            f"{r['peak_child_mb']:.1f}", r["latents_reused"], int(r["n_dump"] or 0), int(r["items"] or 0)])
        written.append(p)
    mem_rows = []
    if inf and inf.get("memory_mb"):
        m = inf["memory_mb"]
        mem_rows += [("inference_process_rss_before_models_mb", m["rss_before_models"]),
                     ("inference_process_rss_after_model_load_mb", m["rss_after_model_load"]),
                     ("inference_models_footprint_mb", m["models_footprint"]),
                     ("inference_process_rss_after_calls_mb", m["rss_after_calls"]),
                     ("inference_process_peak_rss_mb", m["peak_rss"])]
    if rt and rt["runs"]:
        mem_rows.append(("retrain_child_peak_rss_mb", max(r["peak_child_mb"] for r in rt["runs"])))
    if mem_rows:
        p = out_dir / f"bench_{stamp}_memory.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["measure", "mb"])
            for k, v in mem_rows:
                w.writerow([k, f"{v:.1f}" if v is not None else ""])
        written.append(p)
    print("\nmeasurements written:")
    for p in written:
        print(f"  {p}")


if __name__ == "__main__":
    sys.exit(main())
