# Recompute the latents of the last collision dump with the finetune pipeline's
# own code (the path used when no latents were dumped) and compare them index
# by index with latents.npy written by the node. Run from milkv/ (PC or board):
#   python3 -m duos_node.tests.check_dumped_latents [collision_dir]
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import training_quantization.continual_learning.env_safety  # noqa: F401
import torch
from training_quantization.continual_learning.setup_from_config import setup
from training_quantization.continual_learning.latent_utils_min import compute_latent_buffer_for_samples
from training_quantization.continual_learning.lr_data import list_pairs_collision
from training_quantization.continual_learning.samples import CollisionSample
from training_quantization.continual_learning.compat import encoder_fingerprint
from training_quantization.model.gate_classifier_PyTorch_model import GateClassifier

TQ = Path(__file__).resolve().parents[2] / "training_quantization"
cfg = TQ / "continual_learning" / "config.json"
leaf = Path(sys.argv[1]) if len(sys.argv) > 1 else TQ / "collision_dataset" / "train" / "collision_0" / "no_gate"

dc = setup(str(cfg), GateClassifier)          # same model/prep as the finetune (latest .pt, frozen encoder)
triples = list_pairs_collision(leaf)
samples = [CollisionSample(id=i, img_path=ip, tof_path=tp, label=0) for i, (ip, tp, _) in enumerate(triples)]
meta = json.loads((leaf / "latents_meta.json").read_text())
Z_dump = np.load(leaf / "latents.npy")
print(f"dump: {len(samples)} frame pairs, latents.npy {Z_dump.shape}, tap={meta['tap']}, encoder_fp={meta['encoder_fp'][:10]}, model={meta['model']}")
fp = encoder_fingerprint(dc.original_model, dc.latent_tap)
print(f"finetune base model: {dc.original_model_ckpt.name}, encoder_fp={fp[:10]}, match={fp == meta['encoder_fp']}")
buf = compute_latent_buffer_for_samples(samples=samples, model=dc.original_model, data_config=dc,
                                        device=dc.device, latent_tap=dc.latent_tap)
Z_ref = buf.Z_all_t.cpu().numpy()
assert Z_ref.shape == Z_dump.shape, (Z_ref.shape, Z_dump.shape)
per_frame = np.abs(Z_ref - Z_dump).reshape(len(samples), -1).max(axis=1)
print(f"max |Z_pipeline - Z_node| over all frames: {per_frame.max():.3e}   (mean {per_frame.mean():.3e})")
if len(samples) > 1:
    off = np.abs(Z_ref[1:] - Z_dump[:-1]).reshape(len(samples) - 1, -1).max(axis=1).min()
    print(f"smallest difference against the neighbouring frame (should be >> 0): {off:.3e}")
ok = per_frame.max() < 1e-4
print("RESULT:", "OK, node latents == pipeline latents, frame by frame" if ok else "MISMATCH")
sys.exit(0 if ok else 1)
