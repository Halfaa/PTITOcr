"""
Diagnose a broken OCR pipeline.

PaddleOCR reports creation failures as "a dependency error occurred during
pipeline creation", which names neither the package nor the real exception.
This script reproduces the failure with the traceback intact and prints the
versions that matter -- numpy above all, which paddlex pins below 2.0 and
which any later `pip install` can silently upgrade.

Usage (from the venv you want to test):
    python scripts/diagnose_env.py
"""

import importlib.metadata
import sys
import traceback

WATCH = ["numpy", "opencv-python", "opencv-contrib-python",
         "opencv-python-headless", "paddlepaddle", "paddleocr", "paddlex",
         "torch", "torchvision", "transformers", "pillow", "apted", "PyMuPDF"]


def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "-"


print(f"Python     : {sys.version.split()[0]}")
print(f"executable : {sys.executable}\n")

for name in WATCH:
    v = version(name)
    flag = ""
    if name == "numpy" and v != "-" and int(v.split(".")[0]) >= 2:
        flag = "  <-- paddlex requires numpy < 2, this is very likely the cause"
    print(f"  {name:<16} {v}{flag}")

print("\n--- trying to create the pipelines ---")

for label, factory in (
    ("PaddleOCR-VL", lambda: __import__("paddleocr").PaddleOCRVL(pipeline_version="v1")),
    ("PP-StructureV3", lambda: __import__("paddleocr").PPStructureV3(enable_mkldnn=False)),
):
    try:
        factory()
        print(f"  {label}: OK")
    except Exception:
        print(f"  {label}: FAILED")
        traceback.print_exc()
        print()
