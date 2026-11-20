"""Put tools/ first on sys.path. Tests do `import _path` first.

A test run as a plain script has tests/ on sys.path, so this module is
importable without pytest or a conftest.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
