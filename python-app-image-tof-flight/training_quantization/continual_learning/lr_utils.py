from __future__ import annotations
from pathlib import Path
from typing import Sequence, List
from datetime import datetime

def make_unique_run_id() -> str:
    """Creates a unique ID for the run (timestamp)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def sort_numeric_then_lex(paths: Sequence[Path]) -> List[Path]:
    """
    Sorts first by number (if the stem is numeric), otherwise lexically.
    """
    def keyfun(p: Path):
        stem = p.stem
        return (0, int(stem)) if stem.isdigit() else (1, stem)
    return sorted(paths, key=keyfun)

def find_latest_checkpoint(root: Path) -> Path:
    root = root.resolve()
    if root.is_file():
        return root
    if not root.exists():
        raise FileNotFoundError(f"Model directory not found: {root}")
    pts = [p for p in root.iterdir() if p.is_file() and p.suffix == ".pt"]
    if not pts:
        raise FileNotFoundError(f"No .pt files found in {root}")
    pts.sort(key=lambda p: p.stat().st_mtime)
    return pts[-1]