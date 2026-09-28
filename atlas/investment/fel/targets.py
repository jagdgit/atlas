"""Target specs — metadata only in FEL.0 (PIT labels land in FEL.2)."""

from __future__ import annotations

from atlas.investment.fel.contracts import DecisionType


class FwdRet5d:
    target_id = "fwd_ret_5d"
    version = "1"
    decision_type: DecisionType = "buy_name"
    horizon = "5d"


class RankInUniverse:
    target_id = "rank_in_universe"
    version = "1"
    decision_type: DecisionType = "buy_name"
    horizon = "cross_section"


class PDrawdown:
    target_id = "p_drawdown"
    version = "1"
    decision_type: DecisionType = "size_name"
    horizon = "path"


def seed_targets() -> list[object]:
    return [FwdRet5d(), RankInUniverse(), PDrawdown()]
