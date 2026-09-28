"""FEL model plugins — wraps first; reserved sockets ``available()=False``."""

from atlas.investment.fel.models.baselines import (
    ErPrototypePlugin,
    RankingV1Plugin,
    RulesSmaRsiPlugin,
)
from atlas.investment.fel.models.linear_features import (
    BASELINE_MOM_RS_ID,
    CANDIDATE_MOM_RS_VOL_ID,
    LinearFeatureScorePlugin,
)
from atlas.investment.fel.models.reserved import RESERVED_MODEL_IDS, reserved_model_plugins

__all__ = [
    "BASELINE_MOM_RS_ID",
    "CANDIDATE_MOM_RS_VOL_ID",
    "ErPrototypePlugin",
    "LinearFeatureScorePlugin",
    "RankingV1Plugin",
    "RESERVED_MODEL_IDS",
    "RulesSmaRsiPlugin",
    "reserved_model_plugins",
]
