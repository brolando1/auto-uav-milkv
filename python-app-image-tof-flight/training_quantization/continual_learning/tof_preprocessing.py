import numpy as np
import cv2
from typing import Optional, Tuple

TOF_ROWS_CNN = 21
TOF_COLS_CNN = 21
MEAN_TOF = 2.7159   # meters
STD_TOF = 0.6062 

def parse_tof8x8_line(line: str) -> Optional[Tuple[int, np.ndarray]]:
    """
    Expected:
      TOF8X8,seq,v0,v1,...,v63
    where v* are mm.
    Returns:
      (seq, arr8x8_mm_float32) or None
    """
    s = line.strip()
    if not s.startswith("TOF8X8,"):
        return None
    parts = s.split(",")
    # "TOF8X8" + seq + 64 values = 66 fields
    if len(parts) < 66:
        return None
    try:
        seq = int(parts[1])
        vals = [int(x) for x in parts[2:66]]
    except Exception:
        return None
    if len(vals) != 64:
        return None
    arr = np.array(vals, dtype=np.float32).reshape(8, 8)
    return seq, arr


def tof_apply_orientation(
    tof_8x8: np.ndarray,
    *,
    transpose: bool,
    flip_x: bool,
    flip_y: bool,
) -> np.ndarray:
    """
    Optional orientation fixes (OFF by default).
    - transpose: swap axes
    - flip_x: horizontal flip (left-right)
    - flip_y: vertical flip (top-bottom)
    """
    out = tof_8x8
    if transpose:
        out = out.T
    if flip_x:
        out = np.fliplr(out)
    if flip_y:
        out = np.flipud(out)
    return out.copy() if out is tof_8x8 else out


def tof_21x21_from_8x8_meters(tof_8x8_m: np.ndarray) -> np.ndarray:
    return cv2.resize(
        tof_8x8_m.astype(np.float32),
        dsize=(TOF_COLS_CNN, TOF_ROWS_CNN),
        interpolation=cv2.INTER_NEAREST,
    ).astype(np.float32, copy=False)


def tof_norm_21x21_from_8x8_mm(
    tof_8x8_mm: np.ndarray,
    *,
    transpose: bool = False,
    flip_x: bool = False,
    flip_y: bool = False,
    invalid_mm_to_mean: bool = True,
) -> np.ndarray:
    """
    - Input: 8x8 in mm
    - Convert to meters
    - Optional orientation fixes
    - Upsample to 21x21 (nearest)
    - Standardize: (m - MEAN_TOF) / STD_TOF
    """
    mm = tof_apply_orientation(tof_8x8_mm, transpose=transpose, flip_x=flip_x, flip_y=flip_y).astype(np.float32)

    # Handle invalids (-1, 0, <=0) if present
    if invalid_mm_to_mean:
        mm = mm.copy()
        mm[mm <= 0.0] = float(MEAN_TOF) * 1000.0  # mean in mm

    m = mm / 1000.0
    m = np.clip(m, 0.05, 10.0).astype(np.float32, copy=False)

    tof_21 = tof_21x21_from_8x8_meters(m)
    return (tof_21 - float(MEAN_TOF)) / max(1e-12, float(STD_TOF))