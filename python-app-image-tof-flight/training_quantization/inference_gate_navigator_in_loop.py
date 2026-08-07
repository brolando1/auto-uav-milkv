import os
import cv2
import glob
import numpy as np
import tensorflow as tf

import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing
import training_quantization.continual_learning.img_preprocessing as img_preprocessing

TOF_ROWS = 8
TOF_COLS = 8
TOF_ROWS_CNN = 21
TOF_COLS_CNN = 21

IMG_ROWS_CNN = 168
IMG_COLS_CNN = 168

class InferenceGateNavigatorInLoop:
    def __init__(self, image_lock, tof_lock):
        self.image_lock = image_lock
        self.tof_lock = tof_lock

        base_dir = os.path.dirname(__file__)

        model_path = os.path.abspath(os.path.join(base_dir, 'model/gate_navigator_model.tflite'))

        self.interpreter = tf.lite.Interpreter(model_path = model_path, num_threads=2)
        self.interpreter.allocate_tensors()

        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        self.cam_details = None
        self.tof_details = None
        for detail in self.input_details:
            if 168 in detail['shape']:
                self.cam_details = detail
            elif 21 in detail['shape']:
                self.tof_details = detail

        self.cam_input_index = None
        self.tof_input_index = None

        for input_detail in self.input_details:
            shape = input_detail['shape']
            if shape[1] == 168 and shape[2] == 168:
                self.cam_input_index = input_detail['index']
            elif shape[1] == 21 and shape[2] == 21:
                self.tof_input_index = input_detail['index']
        self.image_input_data = None
        self.tof_input_data = None
        
    
    def _predict_pre_step(self, latest_cam, latest_tof):
        self.tof_lock.acquire()
        try:
            if latest_cam is None or latest_tof is None:
                return False
        finally:
            self.tof_lock.release()
        self.preprocessing_and_set_sample(latest_cam, latest_tof)
        return True
    
    def predict_navigation(self):
        """ Predict yaw rate to fly towards the gate """

        # run gate navigator
        self.interpreter.set_tensor(
            self.cam_details["index"], self.image_input_data
        )
        self.interpreter.set_tensor(
            self.tof_details["index"], self.tof_input_data
        )
        self.interpreter.invoke()

        self.out_meta = self.output_details[0]
        pred_yaw = (
            self.interpreter.get_tensor(self.out_meta["index"])[0]
        )

        # tensorflow-lite dequantization
        output_scale, output_zero_point = self.out_meta["quantization"]
        float_pred_yaw = (pred_yaw.astype(np.float32) - output_zero_point) * output_scale

        return float_pred_yaw
    
    def preprocessing_and_set_sample(self, img_decoded, tof_arr):

        # camera and tof preprocessing
        camera_image_168x168_norm = img_preprocessing.camera_norm_168(img_decoded,preproc='none')
        tof_matrix_21x21_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_arr)

        camera_image_quant = np.resize(
            camera_image_168x168_norm, (1, IMG_ROWS_CNN, IMG_COLS_CNN, 1)
        )
        tof_matrix_21x21_quant = np.resize(
            tof_matrix_21x21_norm, (1, TOF_ROWS_CNN, TOF_COLS_CNN, 1)
        )
    
        # tensorflow-lite camera quantization
        input_scale, input_zero_point = self.cam_details["quantization"]
        self.image_input_data  = (camera_image_quant / input_scale + input_zero_point).astype(self.cam_details['dtype'])

        # tensorflow-lite ToF quantization
        input_scale, input_zero_point = self.tof_details["quantization"]
        self.tof_input_data = (
            tof_matrix_21x21_quant / input_scale + input_zero_point
        ).astype(self.tof_details['dtype'])
    

