# OpenCV drawing helpers for the ground station viewer: text overlay, ToF
# heatmaps, the model-input debug panels and the realtime p(gate) plot.
# (Kept from the old local opencv_viewer.py; everything else in that file ran
# inference/training on the PC and now lives on the Duo S.)

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np


# =============================================================================
# UI helpers
# =============================================================================
def overlay_text(img_bgr: np.ndarray, lines: List[str]) -> np.ndarray:
    out = img_bgr.copy()
    y = 26
    for line in lines:
        cv2.putText(out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        y += 28
    return out


def render_tof_heatmap_panel(
    tof_2d: np.ndarray,
    *,
    panel_size: int = 320,
    vmin: float,
    vmax: float,
    draw_grid: bool = True,
    title: str = "ToF",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    arr = tof_2d.astype(np.float32, copy=False)
    arr = np.clip(arr, vmin, vmax)

    u = (arr - float(vmin)) / max(1e-9, float(vmax - vmin))
    u8 = np.clip(u * 255.0, 0.0, 255.0).astype(np.uint8)

    color = cv2.applyColorMap(u8, cv2.COLORMAP_TURBO)
    panel = cv2.resize(color, (panel_size, panel_size), interpolation=cv2.INTER_NEAREST)

    if draw_grid and tof_2d.shape[0] <= 32 and tof_2d.shape[1] <= 32:
        step_y = panel_size // max(1, int(tof_2d.shape[0]))
        step_x = panel_size // max(1, int(tof_2d.shape[1]))
        for i in range(1, int(tof_2d.shape[1])):
            x = i * step_x
            cv2.line(panel, (x, 0), (x, panel_size - 1), (0, 0, 0), 1)
        for i in range(1, int(tof_2d.shape[0])):
            y = i * step_y
            cv2.line(panel, (0, y), (panel_size - 1, y), (0, 0, 0), 1)

    cv2.rectangle(panel, (0, 0), (panel_size - 1, 28), (0, 0, 0), -1)
    cv2.putText(panel, title, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if bottom_text:
        cv2.rectangle(panel, (0, panel_size - 28), (panel_size - 1, panel_size - 1), (0, 0, 0), -1)
        cv2.putText(panel, bottom_text, (10, panel_size - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return panel

def render_tof_heatmap_panel_mm(
    tof_8x8_mm: np.ndarray,
    *,
    panel_size: int = 320,
    vmin_mm: float = 200.0,
    vmax_mm: float = 4000.0,
    draw_grid: bool = True,
    title: str = "ToF 8x8 (mm)",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    return render_tof_heatmap_panel(
        tof_8x8_mm,
        panel_size=panel_size,
        vmin=vmin_mm,
        vmax=vmax_mm,
        draw_grid=draw_grid,
        title=title,
        bottom_text=bottom_text,
    )

def resize_keep_aspect(img: np.ndarray, target_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    if h == target_h:
        return img
    new_w = int(round(w * (target_h / float(h))))
    return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_AREA)


def gray_to_bgr(gray_2d: np.ndarray) -> np.ndarray:
    g = gray_2d.astype(np.uint8, copy=False)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def render_camera_input_panel(
    cam_uint8_168: np.ndarray,
    *,
    panel_size: int = 320,
    title: str = "Camera model input (168x168)",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    img = gray_to_bgr(cam_uint8_168)
    panel = cv2.resize(img, (panel_size, panel_size), interpolation=cv2.INTER_AREA)
    cv2.rectangle(panel, (0, 0), (panel_size - 1, 28), (0, 0, 0), -1)
    cv2.putText(panel, title, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

    if bottom_text:
        cv2.rectangle(panel, (0, panel_size - 28), (panel_size - 1, panel_size - 1), (0, 0, 0), -1)
        cv2.putText(panel, bottom_text, (10, panel_size - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return panel


def make_debug_grid_2x2(
    p00: np.ndarray,
    p01: np.ndarray,
    p10: np.ndarray,
    p11: np.ndarray,
) -> np.ndarray:
    target_h = max(p00.shape[0], p01.shape[0], p10.shape[0], p11.shape[0])
    a = resize_keep_aspect(p00, target_h)
    b = resize_keep_aspect(p01, target_h)
    c = resize_keep_aspect(p10, target_h)
    d = resize_keep_aspect(p11, target_h)

    top_h = max(a.shape[0], b.shape[0])
    bot_h = max(c.shape[0], d.shape[0])

    a = resize_keep_aspect(a, top_h)
    b = resize_keep_aspect(b, top_h)
    c = resize_keep_aspect(c, bot_h)
    d = resize_keep_aspect(d, bot_h)

    top = np.hstack([a, b])
    bottom = np.hstack([c, d])

    if top.shape[1] != bottom.shape[1]:
        target_w = max(top.shape[1], bottom.shape[1])
        top = cv2.resize(top, (target_w, top.shape[0]), interpolation=cv2.INTER_AREA)
        bottom = cv2.resize(bottom, (target_w, bottom.shape[0]), interpolation=cv2.INTER_AREA)

    return np.vstack([top, bottom])


def hstack_resize_to_height(left_bgr: np.ndarray, right_bgr: np.ndarray, height: int) -> np.ndarray:
    def resize_keep_aspect(img: np.ndarray, target_h: int) -> np.ndarray:
        h, w = img.shape[:2]
        if h == target_h:
            return img
        new_w = int(round(w * (target_h / float(h))))
        return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_CUBIC)

    L = resize_keep_aspect(left_bgr, height)
    R = resize_keep_aspect(right_bgr, height)
    return np.hstack([L, R])


# =============================================================================
# Real-time plot (OpenCV-based)
# =============================================================================
class RealTimeProbabilityPlot:
    def __init__(self, *, history_s: float = 30.0, width: int = 640, height: int = 240, title: str = "p(gate) vs time") -> None:
        self.history_s = float(max(0.5, history_s))
        self.width = int(max(200, width))
        self.height = int(max(150, height))
        self.title = str(title)

        self._t: Deque[float] = deque()
        self._p: Deque[float] = deque()

        self.m_left = 55
        self.m_right = 15
        self.m_top = 30
        self.m_bottom = 35

    def add(self, t_sec: float, p: float) -> None:
        t = float(t_sec)
        pv = max(0.0, min(1.0, float(p)))
        self._t.append(t)
        self._p.append(pv)

        t_min = t - self.history_s
        while self._t and self._t[0] < t_min:
            self._t.popleft()
            self._p.popleft()

    def _map_x(self, t: float, t0: float, t1: float) -> int:
        x0, x1 = self.m_left, self.width - self.m_right
        if t1 <= t0 + 1e-9:
            return int(x1)
        u = (t - t0) / (t1 - t0)
        u = max(0.0, min(1.0, u))
        return int(x0 + u * (x1 - x0))

    def _map_y(self, p: float) -> int:
        y0, y1 = self.height - self.m_bottom, self.m_top
        pv = max(0.0, min(1.0, float(p)))
        return int(y0 - pv * (y0 - y1))

    def render(self) -> np.ndarray:
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (18, 18, 18)

        x0, x1 = self.m_left, self.width - self.m_right
        y0, y1 = self.height - self.m_bottom, self.m_top

        cv2.rectangle(img, (x0, y1), (x1, y0), (80, 80, 80), 1)
        cv2.putText(img, self.title, (x0, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1, cv2.LINE_AA)

        for yt, lab in [(0.0, "0.0"), (0.5, "0.5"), (1.0, "1.0")]:
            yy = self._map_y(yt)
            cv2.line(img, (x0, yy), (x1, yy), (45, 45, 45), 1)
            cv2.putText(img, lab, (8, yy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        if not self._t:
            cv2.putText(img, "waiting for data...", (x0 + 10, (y0 + y1) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
            return img

        t_last = float(self._t[-1])
        t0w, t1w = t_last - self.history_s, t_last

        tick_count = 4
        for i in range(tick_count + 1):
            rel = -self.history_s + (self.history_s * i / tick_count)
            tt = t_last + rel
            xx = self._map_x(tt, t0w, t1w)
            cv2.line(img, (xx, y0), (xx, y0 + 5), (200, 200, 200), 1)
            cv2.putText(img, f"{int(rel):d}s", (xx - 16, y0 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        pts: List[Tuple[int, int]] = []
        for t, p in zip(self._t, self._p):
            pts.append((self._map_x(float(t), t0w, t1w), self._map_y(float(p))))

        if len(pts) >= 2:
            cv2.polylines(img, [np.array(pts, dtype=np.int32)], isClosed=False, color=(0, 255, 0), thickness=2)
        else:
            cv2.circle(img, pts[0], 2, (0, 255, 0), -1)

        p_last = float(self._p[-1])
        cv2.putText(img, f"p={p_last:.3f}", (x1 - 90, y1 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)
        return img
