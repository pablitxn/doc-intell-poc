"""Resolve repository resources independently of each test module's depth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
