"""
This script is used to check the CNN testing performance live from webots simulation

author: Konstantin Kalenberg
"""

# essentials
import os
import wandb
import cv2
import math
import numpy as np

# torch
import torch
import torchvision.transforms as transforms

# imav challenge
from .model.imav_challenge_models import GateNavigator, GateClassifier

class InferenceComputerInLoop:
    def __init__(self, image_lock, tof_lock):
        # Threading safety
        self.image_lock = image_lock
        self.tof_lock = tof_lock

        # Parameters
        self.data_loading_path_image = 'logger/data/image.npy'
        self.data_loading_path_tof = 'logger/data/tof.npy'
        self.verbose = False

        # Standardizer values
        self.cnt_im = 0
        self.fst_moment_im = torch.empty(1)
        self.snd_moment_im = torch.empty(1)
        self.to_tensor_transform = transforms.ToTensor()

        # Flying room values
        # self.mean_image = 0.3078
        # self.std_image = 0.2321

        # Sim values
        self.mean_image = 0.2142
        self.std_image = 0.0991
        self.mean_tof = 2.7051
        self.std_tof = 0.6042

        self.transform_image = transforms.Compose([transforms.ToTensor(), transforms.Normalize(mean=[self.mean_image], std=[self.std_image])])
        self.transform_tof = transforms.Compose([transforms.ToTensor(), transforms.Normalize(mean=[self.mean_tof], std=[self.std_tof])])
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        # # Load pre-trained CNN Model from wandb artifact
        # # Run once with internet connection on to download artifact locally, afterwards comment lines below again since
        # # wandb needs internet, but we are connected to drone wifi.
        # model_loading_path_gate_navigator = 'kkalenbe/kk_master_thesis/best_model_gate_navigator:v10'  # Wandb artifact path
        # model_loading_path_gate_classifier = 'kkalenbe/kk_master_thesis/best_model_gate_classifier:v51'  # Wandb artifact path
        # wandb.init(project="trash", group="")
        # full_state_dict_dir_gate_navigator = wandb.use_artifact(model_loading_path_gate_navigator).download()
        # full_state_dict_dir_gate_classifier = wandb.use_artifact(model_loading_path_gate_classifier).download()

        # Load gate classifier model from wandb artifact
        full_state_dict_dir_gc = 'artifacts/best_model_gate_classifier:v51'
        files = os.listdir(full_state_dict_dir_gc)
        full_state_dict_gc = None
        if torch.cuda.is_available():
            full_state_dict_gc = torch.load(full_state_dict_dir_gc + '/' + files[0])
        else:
            full_state_dict_gc = torch.load(full_state_dict_dir_gc + '/' + files[0], map_location=torch.device('cpu'))

        self.gate_classification_model = GateClassifier(num_channels_start=full_state_dict_gc['num_channels_start'],
                                                        dropout_p=full_state_dict_gc['dropout_p'])
        self.gate_classification_model.load_state_dict(state_dict=full_state_dict_gc['gate_classifier_state_dict'], strict=True)

        # Load gate navigator model from wandb artifact
        full_state_dict_dir_gn = 'artifacts/best_model_gate_navigator:v10'
        files = os.listdir(full_state_dict_dir_gn)
        full_state_dict_gn = None
        if torch.cuda.is_available():
            full_state_dict_gn = torch.load(full_state_dict_dir_gn + '/' + files[0])
        else:
            full_state_dict_gn = torch.load(full_state_dict_dir_gn + '/' + files[0], map_location=torch.device('cpu'))

        self.gate_navigation_model = GateNavigator(num_channels_start=full_state_dict_gn['num_channels_start'],
                                                   dropout_p=full_state_dict_gn['dropout_p'])
        self.gate_navigation_model.load_state_dict(state_dict=full_state_dict_gn['gate_navigator_state_dict'], strict=True)

        # Set models to inference mode
        self.gate_classification_model.eval()
        self.gate_navigation_model.eval()

        # Data parameters
        self.tof_width = 21
        self.tof_height = 21

        # Sample for inference
        self.image = None
        self.tof = None

    def predict_pre_step(self):
        """ Processes saved sample by loading image and tof """
        # Load image
        self.image_lock.acquire()
        image_new = np.load(self.data_loading_path_image)
        self.image_lock.release()

        # Load tof
        self.tof_lock.acquire()
        tof_new = np.load(self.data_loading_path_tof)
        self.tof_lock.release()

        # Preprocess image and tof
        self.preprocess_and_set_sample(image_new, tof_new)

    def predict_classification(self):
        """ Predict probability of seeing a gate """
        # Run inference on sample set in predict_pre_step() call
        pred_class = self.gate_classification_model(self.image, self.tof)
        return pred_class.item()

    def predict_navigation(self):
        """ Predict yaw rate to fly towards the gate """
        # Run inference on sample set in predict_pre_step() call
        pred_yaw = self.gate_navigation_model(self.image, self.tof)
        return pred_yaw.item()

    def preprocess_and_set_sample(self, image, tof):
        """ Processes image and tof into shape and datatype needed for pytorch inference """
        # Upsample ToF
        tof = cv2.resize(tof, dsize=(self.tof_width, self.tof_height), interpolation=cv2.INTER_NEAREST)

        # Camera image is already resized correctly in camera_logger.py

        # Transform (normalize image and tof) transform to torch tensor and expand dimension
        self.image = self.transform_image(image)[None, :, :, :].to(self.device)
        self.tof = self.transform_tof(tof)[None, :, :, :].to(self.device)

    def compute_image_standardizer_values(self):
        """ Compute image standardizer values for the current scene and print them live """
        # Load image
        self.image_lock.acquire()
        image_new = np.load(self.data_loading_path_image)
        self.image_lock.release()

        # Transform to torch tensor
        image_new = self.to_tensor_transform(image_new)

        _, h, w = image_new.shape
        nb_pixels_im = h * w
        sum = torch.sum(image_new, dim=[1, 2])
        sum_of_square = torch.sum(image_new ** 2, dim=[1, 2])
        self.fst_moment_im = (self.cnt_im * self.fst_moment_im + sum) / (self.cnt_im + nb_pixels_im)
        self.snd_moment_im = (self.cnt_im * self.snd_moment_im + sum_of_square) / (self.cnt_im + nb_pixels_im)
        self.cnt_im += nb_pixels_im

        self.mean_image = self.fst_moment_im.item()
        self.std_image = torch.sqrt(self.snd_moment_im - self.fst_moment_im ** 2).item()

        print('image mean / std: ', self.mean_image, " / ", self.std_image)


