"""
Python adaptation of ToF Obstacle Avoidance algorithm

author: Konstantin Kalenberg

Adapted from https://gitlab.ethz.ch/pbl/fs2022/nano-uav-exploration/tof-obstacle-avoidance
"""

import numpy as np
import sys
from dataclasses import dataclass


@dataclass
class pos_t:
    x: float
    y: float

@dataclass
class zone_t:
    top_left: pos_t
    bottom_right: pos_t

@dataclass
class borders_t:
    top: int
    left: int
    right: int
    bottom: int

@dataclass
class target_t:
    position: pos_t
    borders: borders_t
    min_distance: int
    max_distance: int
    avg_distance: int
    pixels_number: int


# Parameters
GROUND_BORDER = 6
CELLING_BORDER = 2
MIN_PIXEL_NUMBER = 1
# Decision Parameters
DIS_GROUND_MIN = 10  # mm
DIS_CEILING_MIN = 10  # mm
TURN_MAX = 1.0
TURN_SLOW = 0.25
TURN_FAST = 0.5
TURN_NOT = 0.0
VEL_STOP = 0.0
VEL_FEAR = -0.25
VEL_MULTIPLIER = 1.0
VEL_SCALE_MEDIUM = 0.5 * VEL_MULTIPLIER
VEL_SCALE_SLOW = 0.35 * VEL_MULTIPLIER
VEL_UP = 0.2
VEL_DOWN = -0.5
MAX_TURN_RATIO = 0.8
EPSILON = 0.0001
# Constants
ROW = 8
COL = 8
MAX_TARGET_NUM = 6
# ToF
ToF_DISTANCES_LEN = 2*ROW*COL
ToF_TARGETS_DETECTED_LEN = ROW*COL
ToF_TARGETS_STATUS_LEN = ROW*COL
TOF_FPS = 15.0
TOF_PERIOD = 1.0/TOF_FPS

# Process Parameter
MAX_DISTANCE_TO_PROCES = 2000  # mm
HISTORY_LENGTH = 10

# Zones and position parameters
DRONE_ZONE = zone_t(pos_t(3.0, 3.0), pos_t(5.0, 4.0))
CARE_ZONE = zone_t(pos_t(2.0, 2.0), pos_t(5.0, 5.0))
MIDDLE_POS = pos_t(3.0, 3.5)

DIS_REACT = 800  # mm
DIS_SLOW = 500  # mm
DIS_STOP = 300  # mm
DIS_FEAR = 150  # mm

# Global constants
SYS_MAXSIZE = sys.maxsize
SYS_MINSIZE = -sys.maxsize - 1


def avoid_obstacles_tof(tof_lock, tof_image, tof_image_validity):
    # Load tof and tof validity
    # tof_lock.acquire()
    # tof_image = np.load('logger/data/tof.npy')
    # tof_image_validity = np.load('logger/data/tof_validity.npy')
    # tof_lock.release()

    # Change tof_image unit from m --> mm (is already passed in mm in new version)
    # tof_image *= 1000

    # Detect objects
    object_matrices, object_num = count_islands(tof_image_validity)

    # Objects feature extraction
    targets = np.empty(MAX_TARGET_NUM, dtype=target_t)
    for k in range(0, object_num):
        dis_min = SYS_MAXSIZE
        x_sum = 0
        y_sum = 0
        trues_count = 0
        tar_borders = borders_t(SYS_MAXSIZE, SYS_MAXSIZE, SYS_MINSIZE, SYS_MINSIZE)  # top left right bottom

        for i in range(0, ROW):
            for j in range(0, COL):
                if object_matrices[k, i, j] == True:
                    if tof_image[i, j] < dis_min:
                        dis_min = tof_image[i, j]
                    x_sum += i
                    y_sum += j
                    trues_count += 1

                    # Update borders
                    if i < tar_borders.top:
                        tar_borders.top = i
                    if i > tar_borders.bottom:
                        tar_borders.bottom = i
                    if j < tar_borders.left:
                        tar_borders.left = j
                    if j > tar_borders.right:
                        tar_borders.right = j
        new_target = target_t(pos_t(float(x_sum / trues_count), float(y_sum / trues_count)), tar_borders, dis_min, None, None, trues_count)

        targets[k] = new_target

    command_velocity_x, command_velocity_z, command_turn = decision_making(targets, object_num)

    return command_velocity_x, command_velocity_z, command_turn

# The main function that returns count of islands in a given boolean 2D matrix
def count_islands(binary_tof_image):
    object_matrices = np.full((MAX_TARGET_NUM, ROW, COL), False)
    object_num = 0

    # Make a bool array to mark visited cells, initially all cells are unvisited
    visited = np.full((ROW, COL), False)
    old_visited = np.full((ROW, COL), False)

    for i in range(0, ROW):
        for j in range(0, COL):
            if (binary_tof_image[i, j] == True) and (visited[i, j] == False):
                # Save old visited status
                old_visited = np.copy(visited)

                # If a cell with value True is not visited yet, then new island found. Visit all cells in this island.
                visited = dfs(binary_tof_image, i, j, visited)

                # Save new Island positions
                if object_num < MAX_TARGET_NUM:
                    object_matrices[object_num] = np.logical_xor(old_visited, visited)

                    # Increment island count
                    object_num += 1

    return object_matrices, object_num

# A utility function to do DFS for a 2D boolean matrix. It only considers the 8 neighbours as adjacent vertices
def dfs(binary_tof_image, row, col, visited):
    # These arrays are used to get row and column numbers of 8 neighbours of a given cell
    neighbour_num = 8
    row_nbr = np.array([-1, -1, -1, 0, 0, 1, 1, 1])
    col_nbr = np.array([-1, 0, 1, -1, 1, -1, 0, 1])

    # Mark cell as visited
    visited[row, col] = True

    # Recur for all connected neighbours
    for k in range(0, neighbour_num):
        if is_safe(binary_tof_image, row + row_nbr[k], col + col_nbr[k], visited):
            dfs(binary_tof_image, row + row_nbr[k], col + col_nbr[k], visited)

    return visited

# A function to check if a given cell (row, col) can be included in DFS
def is_safe(binary_tof_image, row, col, visited):
    # Row number is in range, column number is in range and value is 1 and not yet visited
    return (row >= 0) and (row < ROW) and (col >= 0) and (col < COL) and (binary_tof_image[row, col] == True and visited[row, col] == False)

def decision_making(targets, object_num):
    # Find the highest priority target
    dis_global_min = SYS_MAXSIZE
    selected_target = -1

    for k in range(0, object_num):
        if (targets[k].min_distance < dis_global_min) and (targets[k].pixels_number > MIN_PIXEL_NUMBER):
            dis_global_min = targets[k].min_distance
            selected_target = k

    if selected_target < 0:  # No big target in front
        decision_making.locked_turn_direction = 0.0
        return 0.5, 0.0, 0.0

    command_velocity_x = 0.0
    command_velocity_z = 0.0
    command_turn = 0.0
    
    min_distance = float(targets[selected_target].min_distance / 1000.0)
    border_right = targets[selected_target].borders.right
    border_bottom = targets[selected_target].borders.bottom
    border_left = targets[selected_target].borders.left
    border_top = targets[selected_target].borders.top
    
    if targets[selected_target].min_distance <= DIS_FEAR:
        command_velocity_x = VEL_FEAR
        command_turn = TURN_NOT
    elif (targets[selected_target].borders.top >= GROUND_BORDER) and \
         (targets[selected_target].min_distance < DIS_GROUND_MIN) and \
         (targets[selected_target].position.x >= MIDDLE_POS.x):  # Check for ground lower
        command_velocity_x = VEL_STOP
        command_velocity_z = VEL_UP
    elif (targets[selected_target].borders.bottom <= CELLING_BORDER) and \
         (targets[selected_target].min_distance < DIS_CEILING_MIN) and \
         (targets[selected_target].position.x < MIDDLE_POS.x):  # Check for celling upper
        command_velocity_x = VEL_STOP
        command_velocity_z = VEL_DOWN
    elif targets[selected_target].min_distance < DIS_REACT:  # Check for front object
        # Scale the distance to the object to be in between 0 and 1 (negative values are zeroed later on)
        command_velocity_x = float(targets[selected_target].min_distance - DIS_STOP) / float(DIS_REACT - DIS_STOP)
        if (targets[selected_target].borders.right >= DRONE_ZONE.top_left.y) and \
            (targets[selected_target].borders.bottom >= DRONE_ZONE.top_left.x) and \
            (targets[selected_target].borders.left <= DRONE_ZONE.bottom_right.y) and \
            (targets[selected_target].borders.top <= DRONE_ZONE.bottom_right.x):  # Object is in drone zone
            if targets[selected_target].min_distance <= DIS_STOP:
                command_velocity_x = VEL_STOP
                command_turn = TURN_MAX
            elif targets[selected_target].min_distance <= DIS_SLOW:
                command_velocity_x *= VEL_SCALE_SLOW
                command_turn = TURN_MAX
            else:
                command_velocity_x = (float(targets[selected_target].min_distance - DIS_SLOW) / (float(DIS_REACT - DIS_STOP))) * VEL_SCALE_MEDIUM + \
                                     (float(DIS_SLOW - DIS_STOP) / float(DIS_REACT - DIS_STOP)) * VEL_SCALE_SLOW
                command_turn = TURN_SLOW
        elif (targets[selected_target].borders.right >= CARE_ZONE.top_left.y)  and \
             (targets[selected_target].borders.bottom >= CARE_ZONE.top_left.x) and \
             (targets[selected_target].borders.left <= CARE_ZONE.bottom_right.y ) and \
             (targets[selected_target].borders.top <= CARE_ZONE.bottom_right.x):  # Object is in care zone
            if targets[selected_target].min_distance <= DIS_STOP:
                command_velocity_x = VEL_STOP
                command_turn = TURN_MAX
            else:
                command_velocity_x *= VEL_SCALE_MEDIUM
                command_turn = TURN_SLOW
        else:
            # The objects are all in the outer regions of the FoV, we should not reduce the speed based on the distance to them
            command_velocity_x = VEL_SCALE_MEDIUM
            command_turn = TURN_NOT
        if targets[selected_target].position.y >= MIDDLE_POS.y:
            command_turn *= -1.0
    else:
        command_velocity_x = VEL_SCALE_MEDIUM
        command_turn = TURN_NOT
    
    if command_turn != 0.0:
        if decision_making.locked_turn_direction == 0.0:
            decision_making.locked_turn_direction = 1.0 if command_turn > 0 else -1.0
        else:
            command_turn = abs(command_turn) * decision_making.locked_turn_direction
    else:
        decision_making.locked_turn_direciton = 0.0

    # Check for special situations
    command_turn = handle_exception_commands(command_turn)

    return command_velocity_x, command_velocity_z, command_turn

def handle_exception_commands(current_turn_command):
    refine_command = current_turn_command
    left_commands = 0
    right_commands = 0

    # Handle convex situations
    for i in range(0, HISTORY_LENGTH):
        if handle_exception_commands.previous_command[i] < -TURN_MAX + EPSILON:
            right_commands += 1
        elif handle_exception_commands.previous_command[i] > TURN_MAX - EPSILON:
            left_commands += 1

    if ((current_turn_command < -TURN_MAX + EPSILON) or (current_turn_command > TURN_MAX - EPSILON)) and \
       (right_commands + left_commands >= (MAX_TURN_RATIO * HISTORY_LENGTH)):
        # Negative means turn to the right
        # (we always want to turn right if we are stuck, to avoid switching between right/left and to maximize explored area)
        if right_commands > left_commands:
            refine_command = -TURN_FAST
        else:
            refine_command = TURN_FAST
    handle_exception_commands.previous_command[handle_exception_commands.previous_command_index] = current_turn_command
    handle_exception_commands.previous_command_index += 1
    handle_exception_commands.previous_command_index %= HISTORY_LENGTH

    return refine_command


handle_exception_commands.previous_command = np.full(HISTORY_LENGTH, 0.0)
handle_exception_commands.previous_command_index = 0

decision_making.locked_turn_direction = 0.0

