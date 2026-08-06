import os
import sys

# Tests import backend modules (retrieval, eval.*) directly, so put the
# backend directory itself on sys.path regardless of where pytest runs from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
