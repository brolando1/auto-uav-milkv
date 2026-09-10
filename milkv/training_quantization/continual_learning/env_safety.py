# BLAS/OMP / NumPy mitigations for “sensitive” CPUs (e.g., RVV on RISC-V)
import os

os.environ.setdefault("NPY_DISABLE_CPU_FEATURES", "V")  # Disable RVV in NumPy
os.environ.setdefault("OPENBLAS_CORETYPE", "generic")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("BLIS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("PYTORCH_NUM_THREADS", "1")
os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")  # no OpenCV thread pool: the node forks the training child
