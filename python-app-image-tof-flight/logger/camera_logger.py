#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#     ||          ____  _ __
#  +------+      / __ )(_) /_______________ _____  ___
#  | 0xBC |     / __  / / __/ ___/ ___/ __ `/_  / / _ \
#  +------+    / /_/ / / /_/ /__/ /  / /_/ / / /_/  __/
#   ||  ||    /_____/_/\__/\___/_/   \__,_/ /___/\___/
#
#  Copyright (C) 2021 Bitcraze AB
#
#  AI-deck demo
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License along with
#  this program; if not, write to the Free Software Foundation, Inc., 51
#  Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#  Demo for showing streamed JPEG images from the AI-deck example.
#
#  By default this demo connects to the IP of the AI-deck example when in
#  Access point mode.
#
#  The demo works by opening a socket to the AI-deck, downloads a stream of
#  JPEG images and looks for start/end-of-frame for the streamed JPEG images.
#  Once an image has been fully downloaded it's rendered in the UI.
#
#  Note that the demo firmware is continously streaming JPEG files so a single
#  JPEG image is taken from the stream using the JPEG start-of-frame (0xFF 0xD8)
#  and the end-of-frame (0xFF 0xD9).

import argparse
import socket, struct, time
import numpy as np
import cv2
from datetime import datetime
import logger.crazyflie_manager as cfm
from logger.camera_tof_pairing import frame_pairing
from training_quantization.inference_gate_classifier_in_loop import InferenceGateClassifierInLoop

def rx_bytes(size, client_socket):
  data = bytearray()
  while len(data) < size:
    data.extend(client_socket.recv(size-len(data)))
  return data

def crazy_camera_logger(time_ref, image_lock):
    imgdata = None
    data_buffer = bytearray()
    # Args for setting IP/port of AI-deck. Default settings are for when
    # AI-deck is in AP mode.
    parser = argparse.ArgumentParser(description='Connect to AI-deck JPEG streamer example')
    parser.add_argument("-n", default="192.168.4.1", metavar="ip", help="AI-deck IP")
    parser.add_argument("-p", type=int, default='5000', metavar="port", help="AI-deck port")
    parser.add_argument('--save', action='store_true', help="Save streamed images")
    args, _ = parser.parse_known_args()

    deck_port = args.p
    deck_ip = args.n

    print("Connecting to socket on {}:{}...".format(deck_ip, deck_port))
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((deck_ip, deck_port))
    print("Socket connected")


    start = time.time()
    last_frame_time = time.time()
    count = 0
    while(1):
        # print("Camera thread started")
        # First get the info
        packetInfoRaw = rx_bytes(4, client_socket)
        # print(packetInfoRaw)
        [length, routing, function] = struct.unpack('<HBB', packetInfoRaw)
        imgHeader = rx_bytes(length - 2, client_socket)
        [magic, width, height, depth, format, size] = struct.unpack('<BHHBBI', imgHeader)

        if magic == 0xBC:
            # Now we start rx the image, this will be split up in packages of some size
            imgStream = bytearray()
            while len(imgStream) < size:
              packetInfoRaw = rx_bytes(4, client_socket)
              [length, dst, src] = struct.unpack('<HBB', packetInfoRaw)
              chunk = rx_bytes(length - 2, client_socket)
              imgStream.extend(chunk)

            count = count + 1

            # --- Calculate instant FPS ---
            # current_time = time.time()
            # dt = current_time - last_frame_time
            # last_frame_time = current_time
            # inst_fps = 1.0 / dt if dt > 0 else 0
            # print(f"FPS Inst: {inst_fps:.2f} | Count: {count}")


            # meanTimePerImage = (time.time()-start) / count
            # print("{}".format(meanTimePerImage))
            # print("{}".format(1/meanTimePerImage))
            # print("{}".format(count))

            if format == 0:
                bayer_img = np.frombuffer(imgStream, dtype=np.uint8)
                bayer_img.shape = (244, 324)

                # Resize to desired dimensions (168x168) by cropping from top
                rows, cols = bayer_img.shape
                start_row = rows - 168
                start_col = cols // 2 - (168 // 2)
                bayer_img_cropped = bayer_img[start_row:start_row + 168, start_col:start_col + 168]

                # Save image
                image_lock.acquire()
                np.save('/home/konstantin/computer-in-loop/python-app-image-tof-logger/deep_learning/data/image.npy', bayer_img_cropped)
                image_lock.release()

                # Show image
                cv2.imshow('Himax camera image cropped to 168x168', bayer_img_cropped)

            else:
              # with open("img.jpeg", "wb") as f:
              #     f.write(imgStream)
              nparr = np.frombuffer(imgStream, np.uint8)
              decoded = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
              frame_pairing(decoded)
              # print(f"[CAMLOG] frame nr.{count} decoded")
              # file_name = round(1000 * (time.time() - time0))
              # save_frame_pair(file_name, cfm.save_matrix, nparr)
              # cv2.imshow('JPEG', decoded)
              # cv2.waitKey(1)