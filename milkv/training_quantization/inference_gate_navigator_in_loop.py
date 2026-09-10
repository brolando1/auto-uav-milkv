import os
import json
import cv2
import numpy as np

import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing
import training_quantization.continual_learning.img_preprocessing as img_preprocessing

TOF_ROWS = 8
TOF_COLS = 8
TOF_ROWS_CNN = 21
TOF_COLS_CNN = 21
IMG_ROWS_CNN = 168
IMG_COLS_CNN = 168


# -----------------------------------------------------------------------------
# Backends. The navigator is an int8 TFLite model (uint8 NHWC in/out). The
# original runtime is used wherever it exists (tflite-runtime, or full
# TensorFlow on a PC); the Duo S (riscv64) has neither, so it runs the same
# network exported to ONNX (QDQ int8, bit-identical outputs, see
# duos_node/tests/test_navigator_backend.py) through onnxruntime.
# -----------------------------------------------------------------------------
class _TFLiteBackend:
    name = "tflite"

    def __init__(self, model_path, interpreter_cls, num_threads=1):
        self.interpreter = interpreter_cls(model_path=model_path, num_threads=num_threads)
        self.interpreter.allocate_tensors()
        ins = self.interpreter.get_input_details()
        outs = self.interpreter.get_output_details()
        self.cam_d = [d for d in ins if 168 in list(d["shape"])][0]
        self.tof_d = [d for d in ins if 21 in list(d["shape"])][0]
        self.out_d = outs[0]
        self.cam_quant = tuple(self.cam_d["quantization"])
        self.tof_quant = tuple(self.tof_d["quantization"])
        self.out_quant = tuple(self.out_d["quantization"])
        self.in_dtype = self.cam_d["dtype"]

    def run(self, cam_u8, tof_u8):
        self.interpreter.set_tensor(self.cam_d["index"], cam_u8)
        self.interpreter.set_tensor(self.tof_d["index"], tof_u8)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.out_d["index"])


class _OnnxBackend:
    name = "onnxruntime"

    def __init__(self, model_path, num_threads=1):
        import onnxruntime as ort
        with open(model_path + ".json", "r", encoding="utf-8") as f:
            meta = json.load(f)
        so = ort.SessionOptions()
        so.intra_op_num_threads = num_threads
        so.inter_op_num_threads = 1
        # EXTENDED fuses Conv+Clip (26.3 -> 24.0 ms on the Duo S, outputs unchanged) but its
        # QDQS8ToU8Transformer trips over this graph ("two nodes with same node name"), so that
        # one transformer is disabled; if the runtime rejects it anyway fall back to BASIC.
        # (Real int8 kernels would not help here: QLinearConv is 1.4-1.8x slower than float
        # conv on this riscv64 build, measured layer by layer.)
        try:
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
            self.session = ort.InferenceSession(model_path, so, providers=["CPUExecutionProvider"],
                                                disabled_optimizers=["QDQS8ToU8Transformer"])
            self.opt_level = "extended"
        except Exception:
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            self.session = ort.InferenceSession(model_path, so, providers=["CPUExecutionProvider"])
            self.opt_level = "basic"
        self.cam_name = [i.name for i in self.session.get_inputs() if 168 in i.shape][0]
        self.tof_name = [i.name for i in self.session.get_inputs() if 21 in i.shape][0]
        self.out_name = self.session.get_outputs()[0].name
        self.cam_quant = (float(meta["cam"]["scale"]), int(meta["cam"]["zero_point"]))
        self.tof_quant = (float(meta["tof"]["scale"]), int(meta["tof"]["zero_point"]))
        self.out_quant = (float(meta["out"]["scale"]), int(meta["out"]["zero_point"]))
        self.in_dtype = np.uint8

    def run(self, cam_u8, tof_u8):
        return self.session.run([self.out_name], {self.cam_name: cam_u8, self.tof_name: tof_u8})[0]


def load_navigator_backend(base_dir, num_threads=1):
    """tflite-runtime -> TensorFlow Lite -> onnxruntime, first one that works."""
    tflite_path = os.path.abspath(os.path.join(base_dir, "model/gate_navigator_model.tflite"))
    onnx_path = os.path.abspath(os.path.join(base_dir, "model/gate_navigator_model.onnx"))
    errors = []
    try:
        from tflite_runtime.interpreter import Interpreter as _Interp
        return _TFLiteBackend(tflite_path, _Interp, num_threads)
    except Exception as e:  # ImportError, or numpy-ABI failures like "_ARRAY_API not found"
        errors.append(f"tflite_runtime: {e}")
    try:
        import tensorflow as tf
        return _TFLiteBackend(tflite_path, tf.lite.Interpreter, num_threads)
    except Exception as e:
        errors.append(f"tensorflow: {e}")
    try:
        return _OnnxBackend(onnx_path, num_threads)
    except Exception as e:
        errors.append(f"onnxruntime: {e}")
    raise RuntimeError("no gate navigator backend available: " + " | ".join(errors))


class InferenceGateNavigatorInLoop:
    def __init__(self, image_lock=None, tof_lock=None):
        self.image_lock = image_lock
        self.tof_lock = tof_lock

        base_dir = os.path.dirname(__file__)
        self.backend = load_navigator_backend(base_dir, num_threads=1)
        self.backend_name = self.backend.name

        self.image_input_data = None
        self.tof_input_data = None

    def _predict_pre_step(self, latest_cam, latest_tof):
        if self.tof_lock is not None:
            self.tof_lock.acquire()
        try:
            if latest_cam is None or latest_tof is None:
                return False
        finally:
            if self.tof_lock is not None:
                self.tof_lock.release()
        self.preprocessing_and_set_sample(latest_cam, latest_tof)
        return True

    def predict_navigation(self):
        """ Predict yaw rate to fly towards the gate """
        # run gate navigator (same uint8 tensors whatever the backend)
        pred_yaw = self.backend.run(self.image_input_data, self.tof_input_data)[0]
        # dequantization
        output_scale, output_zero_point = self.backend.out_quant
        float_pred_yaw = (pred_yaw.astype(np.float32) - output_zero_point) * output_scale
        return float_pred_yaw

    def preprocessing_and_set_sample(self, img_decoded, tof_arr):
        # camera and tof preprocessing
        camera_image_168x168_norm = img_preprocessing.camera_norm_168(img_decoded, preproc='none')
        tof_matrix_21x21_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_arr)

        camera_image_quant = np.resize(
            camera_image_168x168_norm, (1, IMG_ROWS_CNN, IMG_COLS_CNN, 1)
        )
        tof_matrix_21x21_quant = np.resize(
            tof_matrix_21x21_norm, (1, TOF_ROWS_CNN, TOF_COLS_CNN, 1)
        )

        # Quantize to the model's uint8 inputs. The values are clipped to the
        # representable range first: the ToF input covers 0.21..3.0 m (the
        # training data was clipped at 3 m) and a plain uint8 cast of a farther
        # cell would wrap around to a near distance.
        self.image_input_data = self._quantize(camera_image_quant, self.backend.cam_quant)
        self.tof_input_data = self._quantize(tof_matrix_21x21_quant, self.backend.tof_quant)

    def set_sample_from_normalized(self, camera_norm_168, tof_norm_21):
        """Same as preprocessing_and_set_sample, but from arrays the classifier
        already normalized (camera_norm_168 / tof_norm_21x21_from_8x8_mm), so the
        inference loop does not preprocess the frame twice."""
        cam = np.ascontiguousarray(camera_norm_168, dtype=np.float32).reshape(1, IMG_ROWS_CNN, IMG_COLS_CNN, 1)
        tof = np.ascontiguousarray(tof_norm_21, dtype=np.float32).reshape(1, TOF_ROWS_CNN, TOF_COLS_CNN, 1)
        self.image_input_data = self._quantize(cam, self.backend.cam_quant)
        self.tof_input_data = self._quantize(tof, self.backend.tof_quant)

    def _quantize(self, arr, quant):
        scale, zero_point = quant
        q = arr / scale + zero_point
        return np.clip(q, 0, 255).astype(self.backend.in_dtype)
