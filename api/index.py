import sys
import os

# Ensure Vercel can resolve sibling directories (like backend/) regardless of its working directory
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.main import app
