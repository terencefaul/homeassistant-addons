import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "rootfs" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
