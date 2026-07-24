"""Solar plant World Model stub — proves the framework is domain-agnostic (solar-plant test)."""

from __future__ import annotations

from atlas.world_models.framework import StaticWorldModelPack, WorldFact


def solar_plant_pack() -> StaticWorldModelPack:
    facts = [
        WorldFact(
            id="metric.irradiance",
            kind="metric",
            label="Solar irradiance",
            attributes={"unit": "W/m^2", "typical_peak": 1000},
            tags=("irradiance", "solar"),
        ),
        WorldFact(
            id="control.mppt",
            kind="control",
            label="Maximum Power Point Tracking (MPPT)",
            attributes={"purpose": "maximize DC power under varying irradiance"},
            tags=("mppt", "inverter"),
        ),
        WorldFact(
            id="asset.string_inverter",
            kind="asset_class",
            label="String inverter",
            attributes={"dc_ac": "string → AC"},
            tags=("inverter",),
        ),
    ]
    return StaticWorldModelPack(
        id="solar_plant",
        name="Solar Plant (stub)",
        program_hint="solar",
        version="wm.1",
        _facts=facts,
        description=(
            "Minimal solar structure pack so World Models pass the solar-plant test "
            "(Broker Profiles would fail; this pack must load on the same framework)."
        ),
    )
