"""Regression tests for SoDEX learning edge-gate forced pauses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import paper_test_learning as learning


def test_realwide_forced_pause_contains_cross_track_toxic_pairs():
    """REAL-wide toxic pairs must survive gate regeneration.

    RCA 2026-09-10: learning generator overwrote data/paper_test_edge_gate.json
    and emptied REAL-wide pairs_pause, while maturity tracker excluded the same
    toxic pairs. That created evidence/execution divergence. Lock the forced
    pause list so SUI/ADA/HYPE/ONDO cannot be silently re-enabled by regen.
    """
    assert learning.FORCED_PAIRS_PAUSE["REAL-wide"] == {"SUI", "ADA", "HYPE", "ONDO"}
