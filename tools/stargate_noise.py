# ===========================================================================
# Copyright (c) 2025-2026 Politecnico di Torino
# Author: Francesco Giuseppe Gillio
#
# Quick Start:
#
# python stargate_noise.py \
#     path/to/input/ \
#     path/to/output/
# ===========================================================================

import argparse
import os
import sys
from typing import Any, List, Tuple

import numpy as np
import torchvision.transforms as transforms
import torch
from tqdm import tqdm

MEAN_IMAGE = float(0.2031)
STD_IMAGE  = float(0.0930)
MEAN_TOF   = float(2.7159)
STD_TOF    = float(0.6062)


def build_transforms(
    mean_image: float,
    std_image: float,
    mean_tof: float,
    std_tof: float
) -> Tuple[Any, Any]:

    # NOTE: build pipeline transforms

    transform_image = transforms.Compose(
        [
            # transforms.ToTensor(),
            transforms.Lambda(lambda x: (x*std_image) + mean_image),
            transforms.Lambda(lambda x: torch.clamp(x,0.0,1.0)),
            transforms.ColorJitter(brightness=(0.5, 2.0), contrast=(0.5, 2.0)),
            transforms.GaussianBlur(kernel_size=(3, 5)),
            transforms.RandomInvert(),
            transforms.RandomAdjustSharpness(sharpness_factor=10),
            transforms.Normalize(mean=[mean_image], std=[std_image]),
        ]
    )
    
    transform_tof = transforms.Compose(
        [
            # transforms.ToTensor(),
            # transforms.Normalize(mean=[mean_tof], std=[std_tof]),
            transforms.Lambda(lambda x: x)
        ]
    )
    
    return (
        transform_image, 
        transform_tof
    )


def prepare_image(
    array: np.ndarray
) -> np.ndarray:

    # NOTE: handle image dtype

    # if array.dtype != np.uint8 and array.min() >= 0.0 and array.max() <= 255.0:
    #     return array.astype(np.uint8)
    tensor =  torch.from_numpy(array.astype(np.float32))

    if tensor.ndim == 2:
        tensor = tensor.unsqueeze(0)

    elif tensor.ndim == 3 and tensor.shape[-1] == 1:
        tensor = tensor.permute(2,0,1)

    # arr = array.astype(np.float32)
    # if arr.ndim == 2:
    #     arr = np.expand_dim(arr, axis=-1)
    
    return tensor


def prepare_tof(
    array: np.ndarray
) -> np.ndarray:

    # NOTE: handle tof dtype
    tensor = torch.from_numpy(array.astype(np.float32))
    if tensor.ndim == 2:
        tensor = tensor.unsqueeze(0)
    elif tensor.ndim == 3 and tensor.shape[-1] == 1:
        tensor = tensor.permute(2,0,1)
    return tensor
    # arr = array.astype(np.float32)
    # if arr.ndim == 2:
    #     arr = np.expand_dims(arr, axis=-1)

    # return arr


def collect_run_paths(
    input_dir: str
) -> List[Tuple[str, str]]:

    # NOTE: filter numeric directories

    runs = []
    
    run_directories = sorted(
        [
            d for d in os.listdir(input_dir) 
            if os.path.isdir(os.path.join(input_dir, d))
        ],
        # key=lambda x: int(x)
    )
    
    for d in run_directories:
        runs.append(
            (d, os.path.join(input_dir, d))
        )
    
    return runs


def collect_npy_stems(
    run_path: str, 
    subdir: str
) -> List[str]:

    # NOTE: collect npy file stems

    folder = os.path.join(run_path, subdir)
    if not os.path.isdir(folder):
        return []
    
    stems = sorted(
        [
            os.path.splitext(f)[0] for f in os.listdir(folder)
            if f.endswith(".npy")
        ],
        key=lambda x: int(x) if x.isdigit() else x
    )
    
    return stems


def augment_and_save(
    array: np.ndarray,
    transform: Any,
    output_folder: str,
    file_stem: str,
    n_augmentations: int
) -> None:

    # NOTE: augment and save array

    os.makedirs(output_folder, exist_ok=True)
    
    for k in range(n_augmentations):
        tensor = transform(array)
        result = tensor.numpy()

        file_name = f"{file_stem}.npy" if n_augmentations == 1 else f"{file_stem}_aug{k}.npy"
        np.save(os.path.join(output_folder, file_name), result)


def parse_args() -> argparse.Namespace:

    # NOTE: parse cli arguments

    parser = argparse.ArgumentParser(
        description="Generate an offline dataset with augmentation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--input_dir",  
        type=str,
        help="Raw dataset root"
    )
    
    parser.add_argument(
        "--output_dir", 
        type=str,
        help="Output root; same structure as input_dir"
    )
    
    parser.add_argument(
        "--mean_image", 
        type=float, 
        default=MEAN_IMAGE
    )
    
    parser.add_argument(
        "--std_image",  
        type=float, 
        default=STD_IMAGE
    )
    
    parser.add_argument(
        "--mean_tof",   
        type=float, 
        default=MEAN_TOF
    )
    
    parser.add_argument(
        "--std_tof",    
        type=float, 
        default=STD_TOF
    )
    
    parser.add_argument(
        "--n_augmentations", 
        type=int, 
        default=1,
        help="Versions with augmentation for each .npy file."
    )
    
    return parser.parse_args()


def main() -> None:

    # NOTE: main run

    args = parse_args()

    input_dir  = os.path.normpath(args.input_dir)
    output_dir = os.path.normpath(args.output_dir)

    if not os.path.isdir(input_dir):
        print(f"[ERROR] input_dir not available: {input_dir}", file=sys.stderr)
        sys.exit(1)

    (
        transform_image, 
        transform_tof
    ) = build_transforms(
        mean_image=args.mean_image, 
        std_image=args.std_image,
        mean_tof=args.mean_tof,     
        std_tof=args.std_tof,
    )

    print(
        "\n=======================================================\n"
        " Training Pipeline — Dataset Augmentation\n"
        "=======================================================\n"
        f" Input         : {input_dir}\n"
        f" Output        : {output_dir}\n"
        f" Augmentations : {args.n_augmentations} per sample\n"
        "=======================================================\n"
    )

    # ------------------------------
    """ RUN COLLECTION """
    # ---------------

    runs = collect_run_paths(input_dir)
    if not runs:
        print(f"[ERROR] no num folders available in input_dir", file=sys.stderr)
        sys.exit(1)

    print(f"Identified runs: {len(runs)}\n")

    total_samples = int(0)
    total_errors  = int(0)
    errors_detail = []

    for run_id, run_path in runs:
        camera_image_stems = set(collect_npy_stems(run_path, "camera_images"))
        tof_matrix_stems = set(collect_npy_stems(run_path, "tof_distance_array"))
        
        common_stems = sorted(
            camera_image_stems & tof_matrix_stems,
            key=lambda x: int(x) if x.isdigit() else x
        )

        only_camera_image = camera_image_stems - tof_matrix_stems
        only_tof_matrix = tof_matrix_stems - camera_image_stems
        
        if only_camera_image:
            tqdm.write(
                f"  [WARN] run {run_id}: "
                f"{len(only_camera_image)} files only in camera_images"
            )
            
        if only_tof_matrix:
            tqdm.write(
                f"  [WARN] run {run_id}: "
                f"{len(only_tof_matrix)} files only in tof_distance_array (skipped)"
            )

        if not common_stems:
            tqdm.write(
                f"  [SKIP] run {run_id} — "
                "no camera/tof pairs"
            )
            continue

        output_camera_image_dir = os.path.join(output_dir, run_id, "camera_images")
        output_tof_matrix_dir = os.path.join(output_dir, run_id, "tof_distance_array")
        desc = f"Run {run_id}"

        for file_stem in tqdm(common_stems, desc=desc, unit="sample", leave=False):
            try:
                camera_image_raw = np.load(
                    os.path.join(run_path, "camera_images", f"{file_stem}.npy")
                )
                tof_matrix_raw = np.load(
                    os.path.join(run_path, "tof_distance_array", f"{file_stem}.npy")
                )

                camera_image_ready = prepare_image(camera_image_raw)
                tof_matrix_ready = prepare_tof(tof_matrix_raw)

                augment_and_save(
                    camera_image_ready, 
                    transform_image, 
                    output_camera_image_dir, 
                    file_stem, 
                    args.n_augmentations
                )
                
                augment_and_save(
                    tof_matrix_ready,  
                    transform_tof, 
                    output_tof_matrix_dir, 
                    file_stem, 
                    args.n_augmentations
                )

                total_samples += 1

            except Exception as exc:
                total_errors += 1
                errors_detail.append(f"{run_id}/{file_stem}: {exc}")

        tqdm.write(
            f"  ✓  Run {run_id:<4}  "
            f"{len(common_stems)} samples  →  "
            f"{len(common_stems) * args.n_augmentations} files per modality"
        )

    # ------------------------------
    """ REPORT """
    # ---------------

    print(
        "\n=======================================================\n"
        f" Complete: {total_samples} samples, "
        f"{total_samples * args.n_augmentations} files per modality."
    )
    
    if total_errors:
        print(f" Errors ({total_errors}):")
        for msg in errors_detail[:10]:
            print(f"    {msg}")
    else:
        print(" No errors.")
        
    print("=======================================================\n")


if __name__ == "__main__":
    main()