# Checks that the latents the node keeps at inference time are exactly what the
# finetune would recompute, and that the dump/load round trip guards work.
#   python3 -m duos_node.tests.test_latent_reuse            (from milkv/)
import os, sys, tempfile
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import training_quantization.continual_learning.env_safety  # noqa: F401
import torch
from training_quantization.continual_learning.compat import (
    encoder_fingerprint, infer_with_latent, extract_latent, forward_from_latent)
from training_quantization.continual_learning.runtime_utils import (
    load_gate_model, infer_gate_probability, infer_gate_probability_with_latent,
    save_dumped_latents, load_dumped_latents, clear_dumped_latents)

ROOT = Path(__file__).resolve().parents[2] / "training_quantization"
TAP = "post_comb1"


def _ckpts():
    c = [ROOT / "model" / "gate_classifier_model.pt"]
    c += sorted((ROOT / "throwaway_models").glob("*.pt")) if (ROOT / "throwaway_models").exists() else []
    return [p for p in c if p.exists()]


def test_two_stage_forward_matches_full_forward():
    dev = torch.device("cpu")
    model = load_gate_model(str(_ckpts()[0]), dev)
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(5):
        cam = rng.standard_normal((168, 168)).astype(np.float32)
        tof = rng.standard_normal((21, 21)).astype(np.float32)
        p_full = infer_gate_probability(model, cam, tof, dev)
        p_two, z = infer_gate_probability_with_latent(model, cam, tof, dev, TAP)
        worst = max(worst, abs(p_full - p_two))
        assert z.dtype == np.float32 and z.shape == (16, 11, 11), z.shape
    assert worst < 1e-6, f"two-stage forward differs from full forward by {worst}"
    print(f"test_two_stage_forward_matches_full_forward: OK (max |dp| = {worst:.2e})")


def test_fingerprint_stable_across_finetunes():
    dev = torch.device("cpu")
    ck = _ckpts()
    fps = {p.name: encoder_fingerprint(load_gate_model(str(p), dev), TAP) for p in ck}
    base = fps[ck[0].name]
    assert all(len(v) == 40 for v in fps.values())
    fine = [n for n in fps if "finetune" in n]
    for n in fine:
        assert fps[n] == base, f"{n}: pre-tap weights differ from the base model (finetune must not touch them)"
    # a different tap must give a different fingerprint (hash includes the tap)
    assert encoder_fingerprint(load_gate_model(str(ck[0]), dev), "pre_fc") != base
    print(f"test_fingerprint_stable_across_finetunes: OK ({len(ck)} checkpoints, {len(fine)} finetuned, fp {base[:10]})")


def test_dump_roundtrip_and_guards():
    with tempfile.TemporaryDirectory() as d:
        leaf = Path(d) / "no_gate"
        Z = [np.full((16, 11, 11), i, dtype=np.float32) for i in range(7)]
        n = save_dumped_latents(leaf, Z, tap=TAP, encoder_fp="abc", model_name="m.pt")
        assert n == 7
        got, why = load_dumped_latents(leaf, tap=TAP, encoder_fp="abc", expected_n=7)
        assert got is not None and got.shape == (7, 16, 11, 11) and float(got[3, 0, 0, 0]) == 3.0, why
        assert load_dumped_latents(leaf, tap=TAP, encoder_fp="other", expected_n=7)[0] is None
        assert load_dumped_latents(leaf, tap="pre_fc", encoder_fp="abc", expected_n=7)[0] is None
        assert load_dumped_latents(leaf, tap=TAP, encoder_fp="abc", expected_n=6)[0] is None
        clear_dumped_latents(leaf)
        assert load_dumped_latents(leaf, tap=TAP, encoder_fp="abc", expected_n=7)[0] is None
    print("test_dump_roundtrip_and_guards: OK")


def test_onnx_classifier_matches_torch():
    try:
        import onnxruntime  # noqa: F401
        import onnx  # noqa: F401
    except ImportError as e:
        print(f"test_onnx_classifier_matches_torch: SKIPPED ({e})")
        return
    from training_quantization.continual_learning.compat import export_classifier_onnx
    from training_quantization.continual_learning.runtime_utils import OnnxClassifier
    dev = torch.device("cpu")
    ck = _ckpts()[0]
    model = load_gate_model(str(ck), dev)
    with tempfile.TemporaryDirectory() as d:
        path = export_classifier_onnx(model, Path(d) / "m.onnx", TAP)
        oc = OnnxClassifier(path)
        rng = np.random.default_rng(1)
        wp = wz = 0.0
        for _ in range(5):
            cam = rng.standard_normal((168, 168)).astype(np.float32)
            tof = rng.standard_normal((21, 21)).astype(np.float32)
            p_t, z_t = infer_gate_probability_with_latent(model, cam, tof, dev, TAP)
            p_o, z_o = oc.infer(cam, tof)
            wp = max(wp, abs(p_t - p_o)); wz = max(wz, float(np.abs(z_t - z_o).max()))
            assert z_o.shape == z_t.shape and z_o.dtype == np.float32
    assert wp < 1e-5 and wz < 1e-4, (wp, wz)
    print(f"test_onnx_classifier_matches_torch: OK (max |dp| = {wp:.1e}, max |dz| = {wz:.1e})")


if __name__ == "__main__":
    test_two_stage_forward_matches_full_forward()
    test_fingerprint_stable_across_finetunes()
    test_dump_roundtrip_and_guards()
    test_onnx_classifier_matches_torch()
    print("all latent-reuse tests passed")
