# Flight control & ToF and Camera logger & Continual learning

## Project structure

### ToF firmware 

The ToF firmware can be found in `app-tof-logger-tof`. To **build and flash**:
- Move to `app-tof-logger-tof` folder
- In `Makefile` adapt path `CRAZYFLIE_BASE` to your crazyflie firmware
- Run `make clean` to clean exisiting previous builds
- Run `make` to build 
- Put crazyflie into bootloader mode and run `make cload`

### AI-deck Firmware for camera image streaming

The necessary firmware to stream 168 x 168 camera images is in the `wifi-img-streamer` directory. To build it, the `lib` directory is also needed.
In order to **build and flash** the firmware, follow the linked AI-deck tutorials by bitcraze:
- https://www.bitcraze.io/documentation/tutorials/getting-started-with-aideck/ to setup the AI-deck
- https://www.bitcraze.io/documentation/repository/aideck-gap8-examples/master/examples/wifi-streamer/ to configure the crazyflie firmware for AI-deck support and for flashing instructions. Instead of navigating to the aideck-gap8-examples repository just stay in this repository and adjust the `examples/other/wifi-img-streamer` path with `./wifi-img-streamer` in both paths

### Python logger, flight control and continual learning

The code starts in `main.py`, it must be called with different combination of these 4 thread related arguments :

1) `--camera` starts thread to connect to the drone over the wifi and receives camera frames, ensure you are connected to the drone's WiFi
2) `--tof` starts thread for receiving ToF frames
3) `--viewer` starts thread for crazyflie_viewer function in `opencv_viewer.py`, which shows the camera frames, ToF frames and gate probability plots
4) `--keyboard` starts thread that sends commands to the drone

## Viewer

This thread requires the `--camera` and `--tof` threads as well to work.

### Downloading dataset

Finetuning requires the Stargate dataset. If it is not yet downloaded, please run the python file `python-app-image-tof-logger/training_quantization/continual_learning/bootstrap_data.py` which will do it for you. It might take some time to download, please be patient.

### Argument Reference

| Argument | Description |
|----------|-------------|
| `--ckpt` | Starting checkpoint used for inference |
| `--save_collision --buffer_n 90` | Keep the last 90 paired samples in RAM |
| `--buffer_key b` | Press `b` to dump the RAM buffer to disk |
| `--collision_name collisione_0 --collision_label no_gate` | Destination path and label for the saved dataset |
| `--plot` | Enable the live plot of `p(gate)` vs time |
| `--finetune_on_dump` | pressing buffer_key will also start `simulation.py` fine-tuning (as subprocess)|

### Key Controls

When pressing one of those key, be sure to have one of the OpenCv windows in focus.

| Key | Action |
|-----|--------|
| `q` | Quit |
| `d` | Dump current buffer to collision dataset (when `--save_collision` is enabled) |
| `a` | Start continuous recording |
| `b` | Stop continuous recording |

## Keyboard

The board can be controlled manually and autonomously. After running `main.py` with the `--keyboard`argument you have **10 seconds before the drone takes off**. **Make sure you click onto the terminal window again, so that this is focused**, otherwise it might be registered by one of the OpenCv windows.

- **Manual control** :
    - W, A, S, D command velocities as usual
    - Q, E command yaw rates 
    - O, P command height changes
    - K kills the drone making it fall out of the sky

- **Autonomous control** :
    - The I command will make the drone fly autonomously. It will randomly explore its surroundings until it finds a gate and will then proceed to go through it.
    - To **stop the autonomous flying**, one of the commands responsible for manual control should be pressed.

## Experiment procedures

- Move to `python-app-image-tof-logger` in your terminal
- Make sure the Radio channel is set to a high value (>=100) in the cfclient to reduce interference with the wifi streaming
- Start crazyflie and connect computer to crazyflie wifi
- Run `sudo ~/"path_to_your_python_env_dir"/bin/python3 main.py` with the arguments listed above to start the different threads
- **Aborting the programm** : after you landed or killed the drone, make sure to click an OpenCv window and press `q`, afterwards pressing `CTRL-C` multiple times on the terminal to completely stop programm

## Common example command:
  `sudo -E ~/project/venv/bin/python3 main.py --tof --camera --keyboard --viewer --ckpt ./training_quantization/throwaway_models/original_model2.pt --plot --save_collision --finetune_on_dump  --buffer_n 200 --median_k 7 --show_model_inputs`
