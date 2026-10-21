Sophgo SDK headers, pinned to the versions the board's libraries were built from:

- `mpi/` – sophgo/middleware `include/` @ 84b3c487414233e55cc2cf459e9da7955a31c9e1 (matches "MMF Version 84b3c48" on the board)
- `isp/` – sophgo/middleware `modules/isp/include/cv181x/` @ same commit
- `uapi/linux/` – sophgo/osdrv `interdrv/include/{common,chip/cv181x}/uapi/linux/` @ aa542c4 (identical to the 2026-03-24 release)
