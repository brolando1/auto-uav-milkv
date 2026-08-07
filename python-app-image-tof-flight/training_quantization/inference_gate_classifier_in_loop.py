import os
import sys
import cv2
import glob
import numpy as np
import torch


from .model.gate_classifier_PyTorch_model import GateClassifier
import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing
import training_quantization.continual_learning.img_preprocessing as img_preprocessing

class InferenceGateClassifierInLoop:
    def __init__(self, image_lock, tof_lock):
          
          self.image_lock = image_lock
          self.tof_lock = tof_lock

          base_dir = os.path.dirname(__file__)
          self.cam_frames_dir = os.path.abspath(os.path.join(base_dir, 'data/camera_frames'))
          self.tof_frames_dir = os.path.abspath(os.path.join(base_dir, 'data/tof_frames'))

          self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

          self.tof_width = 21
          self.tof_height = 21

          model_ckpt_path = os.path.abspath(os.path.join(base_dir, 'model/gate_classifier_model.pt'))


          ckpt = torch.load(model_ckpt_path, map_location=self.device)
          ncs = ckpt.get("num_channels_start", 4)
          dp = ckpt.get("dropout_p", 0.0)
          self.gate_classification_model = GateClassifier(num_channels_start=ncs, dropout_p=dp)

          self.gate_classification_model.load_state_dict(ckpt['gate_classifier_state_dict'], strict = True)


          self.gate_classification_model.to(self.device)
          self.gate_classification_model.eval()


          self.image_tensor = None
          self.tof_tensor = None

    def _get_latest_pair(self):
         cam_files = glob.glob(os.path.join(self.cam_frames_dir, 'cam*.npy'))
         if not cam_files:
              return None, None
         latest_cam = max(cam_files, key = os.path.getmtime)
         filename_only =os.path.basename(latest_cam)
         timestamp_part = filename_only[3:-4]

         latest_tof = os.path.join(self.tof_frames_dir, f'tof{timestamp_part}.npy')
         if not os.path.exists(latest_tof):
              return None, None
         
         return latest_cam, latest_tof
    
    def _predict_pre_step(self):
         self.tof_lock.acquire()

         try:
              latest_cam, latest_tof = self._get_latest_pair()
              if latest_cam is None or latest_tof is None:
                   return False
              
              image_new = np.load(latest_cam)
              tof_new = np.load(latest_tof)
         finally:
              self.tof_lock.release()
         
         self.preprocessing_and_set_sample(image_new, tof_new)
         return True
    
    def predict_classification(self):
         if self.image_tensor is None or self.tof_tensor is None:
              return 0.0
         with torch.no_grad():
              pred_class = self.gate_classification_model(self.image_tensor, self.tof_tensor)
         return float(pred_class.view(-1)[0].item())
    
    def preprocessing_and_set_sample(self, image_arr, tof_arr):
         
         tof_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_arr)

         cam_decoded = cv2.imdecode(image_arr, cv2.IMREAD_UNCHANGED)
         cam_norm = img_preprocessing.camera_norm_168(cam_decoded, preproc="none")

         self.image_tensor = torch.from_numpy(cam_norm).unsqueeze(0).unsqueeze(0).to(self.device)
         self.tof_tensor = torch.from_numpy(tof_norm).unsqueeze(0).unsqueeze(0).to(self.device)
