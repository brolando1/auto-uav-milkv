import torch

class LatentBuffer:
    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        self.Z_all_t: torch.Tensor | None = None  # [N, ...]
        self.Y_all_t: torch.Tensor | None = None  # [N, 1]
        self.tap = "pre_fc"

    def __len__(self) -> int:
        return int(self.Z_all_t.shape[0]) if self.Z_all_t is not None else 0
