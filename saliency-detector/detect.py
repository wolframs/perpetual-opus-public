#!/usr/bin/env python3
"""
Saliency Detector - Entry point

Run from the saliency-detector directory:
    python detect.py conversation.md
    python detect.py chat.jsonl --top 20 --json
    python detect.py export.md --format consolidation
"""

from saliency.cli import main

if __name__ == "__main__":
    main()
