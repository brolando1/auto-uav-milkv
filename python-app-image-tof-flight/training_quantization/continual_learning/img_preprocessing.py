import cv2
import numpy as np

MEAN_IMAGE = 0.2031
STD_IMAGE = 0.0930
IMG_ROWS_CNN = 168
IMG_COLS_CNN = 168

def crop_hm01b0_to_168(gray_2d: np.ndarray) -> np.ndarray:
    """
    YOUR pipeline:
      - if rows > 244 -> keep [0:244, :]
      - take last 168 rows
      - center-crop 168 columns
    """
    if gray_2d.ndim != 2:
        raise ValueError(f"Expected 2D grayscale, got shape={gray_2d.shape}")

    img = gray_2d
    rows, cols = img.shape

    if rows > 244:
        img = img[0:244, :]
        rows, cols = img.shape

    if rows < 168 or cols < 168:
        raise ValueError(f"Image too small to crop to 168x168: shape={img.shape}")

    x_offset = rows - IMG_ROWS_CNN
    y_offset = cols // 2 - (IMG_COLS_CNN // 2)

    crop = img[x_offset:x_offset + IMG_ROWS_CNN, y_offset:y_offset + IMG_COLS_CNN]
    if crop.shape != (168, 168):
        raise ValueError(f"Crop failed, got shape={crop.shape}")

    return crop


def camera_uint8_168(frame_bgr_or_gray: np.ndarray, *, preproc: str) -> np.ndarray:
    if frame_bgr_or_gray.ndim == 3:
        gray = cv2.cvtColor(frame_bgr_or_gray, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame_bgr_or_gray

    if preproc == "none":
        return gray.astype(np.uint8, copy=False)
    if preproc == "crop":
        return crop_hm01b0_to_168(gray).astype(np.uint8, copy=False)
    if preproc == "resize":
        return cv2.resize(gray, (168, 168), interpolation=cv2.INTER_AREA).astype(np.uint8, copy=False)
    raise ValueError(f"Unknown cam_preproc: {preproc}")


def camera_norm_168(frame_bgr_or_gray: np.ndarray, *, preproc: str) -> np.ndarray:
    """
    camera_image_168x168_norm = ((camera/255.0) - MEAN_IMAGE) / STD_IMAGE
    """
    u8 = camera_uint8_168(frame_bgr_or_gray, preproc=preproc)
    x = u8.astype(np.float32) / 255.0
    return (x - float(MEAN_IMAGE)) / max(1e-12, float(STD_IMAGE))