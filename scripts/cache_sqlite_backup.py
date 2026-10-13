#!/usr/bin/env python3
"""Backward-compatible safe entry point for the local photo cache utility.

The former implementation overwrote every product image URL with a generated
silhouette, even when a real photo could not be downloaded. Use the safe cache
utility instead; it never overwrites the input SQLite file and never invents
product photos.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.cache_catalogue_photo_urls import main

if __name__ == "__main__":
    main()
