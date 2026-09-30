"""Make `tw` and chronology-protocol's `ctp` importable without installing either.

`ctp` is a real dependency: this repository is a chronology-protocol witness
profile, and its observations are ctp objects. If `ctp` is not installed, the
sibling checkout `../chronology-protocol` is used.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sibling = ROOT.parent / "chronology-protocol"
    if not (sibling / "ctp").is_dir():
        raise ImportError("chronology-protocol not installed and no sibling checkout at "
                          f"{sibling}; see README")
    sys.path.insert(0, str(sibling))
