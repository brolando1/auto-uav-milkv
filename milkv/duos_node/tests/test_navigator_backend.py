# The gate navigator must give the same bytes as the original TFLite model,
# whatever backend is available (tflite-runtime / TensorFlow / onnxruntime).
# navigator_tflite_reference.npz holds 8 quantized input pairs and the outputs
# of tf.lite.Interpreter on them.  Run from milkv/ on the PC or the board:
#   python3 -m duos_node.tests.test_navigator_backend
import sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import training_quantization.continual_learning.env_safety  # noqa: F401
from training_quantization.inference_gate_navigator_in_loop import InferenceGateNavigatorInLoop

REF = Path(__file__).with_name("navigator_tflite_reference.npz")


def main():
    f = np.load(REF)
    nav = InferenceGateNavigatorInLoop()
    b = nav.backend
    print(f"backend: {nav.backend_name}")
    for name, got, exp in (("cam", b.cam_quant, f["cam_quant"]), ("tof", b.tof_quant, f["tof_quant"]), ("out", b.out_quant, f["out_quant"])):
        assert abs(got[0] - exp[0]) < 1e-9 and int(got[1]) == int(exp[1]), f"{name} quantization differs: {got} vs {tuple(exp)}"
    outs = []
    t0 = time.perf_counter()
    for i in range(len(f["out_u8"])):
        outs.append(int(b.run(f["cam_u8"][i:i + 1], f["tof_u8"][i:i + 1]).reshape(-1)[0]))
    dt = (time.perf_counter() - t0) / len(outs)
    exp = [int(v) for v in f["out_u8"]]
    assert outs == exp, f"outputs differ from the tflite reference: {outs} vs {exp}"
    print(f"outputs identical to the tflite reference on {len(outs)} samples: {outs}")
    print(f"{dt * 1000:.1f} ms per navigator inference on this machine")
    # end-to-end path with the public API: 8x8 mm ToF + uint8 image, yaw must be finite
    img = (np.random.default_rng(0).random((168, 168)) * 255).astype(np.uint8)
    tof_mm = np.full((8, 8), 1500.0, dtype=np.float32)
    assert nav._predict_pre_step(img, tof_mm)
    yaw = float(nav.predict_navigation()[0])
    assert np.isfinite(yaw) and abs(yaw) < 1.0, yaw
    # far ToF cells (> 3 m) must clip to the model's max distance, not wrap
    tof_far = np.full((8, 8), 9000.0, dtype=np.float32)
    nav.preprocessing_and_set_sample(img, tof_far)
    assert int(nav.tof_input_data.max()) == 255 and int(nav.tof_input_data.min()) == 255, nav.tof_input_data.min()
    print(f"end-to-end yaw for a synthetic frame: {yaw:+.4f} rad/s; far ToF clips to 255 (no wrap)")
    print("navigator backend test passed")


if __name__ == "__main__":
    main()
