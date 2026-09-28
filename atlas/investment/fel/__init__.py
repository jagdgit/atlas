"""Feature & Experiment Laboratory (OI-FEL0) — quantitative scientific instrument.

Not a new OS. Not sklearn/torch in core. Fills stay V1 until Level 10.
"""

from atlas.investment.fel.contracts import (
    FEL_VERSION,
    BlockedUnavailable,
    FeatureGenealogy,
    FeatureMatrix,
    FittedArtifact,
    Predictions,
)
from atlas.investment.fel.registry import FelRegistries, default_fel

__all__ = [
    "FEL_VERSION",
    "BlockedUnavailable",
    "FeatureGenealogy",
    "FeatureMatrix",
    "FelRegistries",
    "FittedArtifact",
    "Predictions",
    "default_fel",
]
