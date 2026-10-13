"""R0 decide-time F&O features: IV/Greeks derived from the traded premium, DTE, time of day."""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.investment import fno_lab_v1 as lab_v1
from atlas.investment.fel.experiments.paper_round_trip import experiences_to_dataset
from atlas.investment.fno_features import bs_price, entry_features, implied_vol
from atlas.investment.lab_experience import _decide_time_features

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 13, 11, 12, tzinfo=IST)


def test_implied_vol_round_trips_black_scholes():
    for right in ("CE", "PE"):
        px = bs_price(right, 22584.0, 22600.0, 14 / 365, 0.18)
        assert math.isclose(implied_vol(right, px, 22584.0, 22600.0, 14 / 365), 0.18, abs_tol=1e-6)


def test_entry_features_on_real_nifty_pack():
    f = entry_features(
        right="PE", spot=22584.0, strike=22600.0, expiry="2026-10-27", premium=246.2,
        other_premium=231.7, indicators={"rsi": 41.0}, sma_margin=-0.03, now=NOW,
    )
    assert 0.13 < f["iv"] < 0.17
    assert -0.55 < f["delta"] < -0.40 and f["theta_per_day"] < 0
    assert math.isclose(f["dte_days"], 14.18, abs_tol=0.01) and f["expiry_week"] is False
    assert f["minutes_since_open"] == 117.0 and f["minutes_to_close"] == 258.0
    assert f["ce_pe_skew"] < 0 and f["sma_margin"] == -0.03
    assert "india_vix" in f["missing"] and "open_interest" in f["missing"]
    assert "sma_fast" in f["missing"]


def test_unknowable_inputs_stay_missing_not_zero():
    f = entry_features(right="CE", spot=22584.0, strike=22600.0, expiry=None, premium=1.0, now=NOW)
    assert "iv" not in f and "dte_days" not in f
    assert {"iv", "delta", "dte_days"} <= set(f["missing"])
    below_intrinsic = entry_features(
        right="CE", spot=23000.0, strike=22600.0, expiry="2026-10-27", premium=100.0, now=NOW
    )
    assert "iv" not in below_intrinsic


def test_features_flow_prediction_to_experience_to_fel_row():
    feats = entry_features(
        right="PE", spot=22584.0, strike=22600.0, expiry="2026-10-27", premium=246.2,
        other_premium=231.7, indicators={"rsi": 41.0, "sma_fast": 22700.0, "sma_slow": 23400.0},
        sma_margin=-0.03, now=NOW,
    )
    pred = lab_v1.build_entry_prediction(
        underlying="NIFTY", option_symbol="NIFTY26OCT22600PE", right="PE", entry_premium=246.2,
        sma_margin=-0.03, control_action="buy", features=feats,
    )
    assert pred["decide_time_features"]["iv"] == feats["iv"]
    exp_feats = _decide_time_features(pred)
    assert exp_feats["iv"] == feats["iv"] and exp_feats["sma_margin"] == -0.03
    ds = experiences_to_dataset(
        [{
            "laboratory_id": "india_fno_learner", "as_of_ist": "2026-10-13",
            "instrument": {"symbol": "NIFTY26OCT22600PE", "asset_class": "fno_option",
                           "nfo_tradingsymbol": "NIFTY26OCT22600PE"},
            "features": exp_feats, "reward": {"value": 100.0, "return_pct": 0.05},
        }],
        laboratory_id="india_fno_learner",
    )
    row = ds["rows"][0]["features"]
    assert row["sma_margin"] == -0.03 and row["iv"] == feats["iv"] and "theta_per_day" in row
    assert "missing" not in row and "iv_method" not in row
    assert ds["feature_ids"][:3] == ["rsi", "sma_fast", "sma_slow"] and "iv" in ds["feature_ids"]
