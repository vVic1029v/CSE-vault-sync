#!/usr/bin/env python3
"""Thin entry point (kept so `python3 main.py ...` keeps working).

All flags and stages live in bsvault.cli; all work in bsvault.pipeline.
"""
from bsvault.cli import main

if __name__ == "__main__":
    main()
