#!/usr/bin/env python3
"""Render build wrapper for the real-photo-only catalogue cache."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--limit",type=int,default=500); ap.add_argument("--discover",action="store_true"); args=ap.parse_args()
    cmd=[sys.executable,str(ROOT/"scripts"/"github_catalogue_image_cache.py"),"--limit",str(args.limit),"--workers","5"]
    raise SystemExit(subprocess.call(cmd,cwd=ROOT))
