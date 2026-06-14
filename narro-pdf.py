#!/usr/bin/env python3
"""Runner script for the modular NarroPDF application."""

import os
import sys

# Add the directory of this script to Python path to resolve src.* imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import main

if __name__ == "__main__":
    sys.exit(main())
