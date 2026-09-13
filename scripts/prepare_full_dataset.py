#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pypdf==6.10.0", "pdfplumber==0.11.9", "pypdfium2==5.13.0", "Pillow==12.3.0"]
# ///
"""Command entry point for the deterministic full-dataset preparation package."""

from pathlib import Path
import sys

# uv runs this file as a standalone script; make the sibling package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preparation.full_dataset import main


if __name__ == '__main__':
    main()
