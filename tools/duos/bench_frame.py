# Runs ON the Duo S (node stopped): isolated per-stage cost of one frame, mean/std over repetitions.
# scp tools/duos/bench_frame.py debian@10.2.250.1:~ && ssh debian@10.2.250.1 python3 bench_frame.py
import os, sys, time, glob
os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, os.path.expanduser("~/milkv"))
import numpy as np, cv2
cv2.setNumThreads(0)
from training_quantization.continual_learning.runtime_utils import OnnxClassifier
from training_quantization.inference_gate_navigator_in_loop import load_navigator_backend

def bench(fn, n=100, reps=5):
    """per-call ms: mean and std over `reps` repetitions of `n` calls each"""
    fn(); fn()
    ms = []
    for _ in range(reps):
        t = time.perf_counter()
        for _ in range(n): fn()
        ms.append((time.perf_counter() - t) / n * 1000)
    m = sum(ms) / len(ms); sd = (sum((x - m) ** 2 for x in ms) / len(ms)) ** 0.5
    return f"{m:6.2f} ms  (std {sd:4.2f}, {reps}x{n})"

# a real dumped frame if there is one, else synthetic
imgs = sorted(glob.glob(os.path.expanduser("~/milkv/**/collision*/**/*.png"), recursive=True))
if imgs:
    gray = cv2.imread(imgs[-1], cv2.IMREAD_GRAYSCALE)
else:
    gray = (np.random.rand(244, 324) * 255).astype(np.uint8)
ok, jpg = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 80])
jpg = np.frombuffer(jpg.tobytes(), np.uint8)
print(f"frame source: {'real ' + os.path.basename(imgs[-1]) if imgs else 'synthetic'} {gray.shape} jpeg {len(jpg)} B")

def decode(): return cv2.imdecode(jpg, cv2.IMREAD_UNCHANGED)
d = decode()
def preproc():
    h, w = d.shape[:2]
    y0, x0 = (h - 168) // 2, (w - 168) // 2
    crop = d[y0:y0+168, x0:x0+168] if h >= 168 and w >= 168 else cv2.resize(d, (168, 168))
    return crop.astype(np.float32) / 255.0
cam = preproc()
tof = (np.random.rand(21, 21).astype(np.float32) * 2.0)

ckpts = sorted(glob.glob(os.path.expanduser("~/milkv/training_quantization/**/*.onnx"), recursive=True))
ckpts = [c for c in ckpts if "navigator" not in c]
clf = OnnxClassifier(ckpts[-1])
print("classifier:", os.path.basename(ckpts[-1]))
nav = load_navigator_backend(os.path.expanduser("~/milkv/training_quantization"))
cam_u8 = np.clip(np.round(cam / nav.cam_quant[0] + nav.cam_quant[1]), 0, 255).astype(np.uint8).reshape(1, 168, 168, 1)
tof_u8 = np.clip(np.round(tof / nav.tof_quant[0] + nav.tof_quant[1]), 0, 255).astype(np.uint8).reshape(1, 21, 21, 1)

print(f"jpeg decode        {bench(decode)}")
print(f"crop+normalize     {bench(preproc)}")
print(f"classifier (ORT)   {bench(lambda: clf.infer(cam, tof))}")
print(f"navigator  (ORT)   {bench(lambda: nav.run(cam_u8, tof_u8))}")

import resource
print(f"bench process peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB (ort sessions + numpy + cv2, no torch)")
