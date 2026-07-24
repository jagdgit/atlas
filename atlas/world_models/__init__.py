"""World Models platform package (WM.1)."""

from atlas.world_models.framework import (
    StaticWorldModelPack,
    WorldFact,
    WorldModelPack,
    WorldModelRegistry,
)
from atlas.world_models.packs import indian_markets_pack, solar_plant_pack


def default_world_model_registry() -> WorldModelRegistry:
    """Boot registry with Market + Solar stub packs (framework + content)."""
    reg = WorldModelRegistry()
    reg.register(indian_markets_pack())
    reg.register(solar_plant_pack())
    return reg


__all__ = [
    "WorldFact",
    "WorldModelPack",
    "WorldModelRegistry",
    "StaticWorldModelPack",
    "indian_markets_pack",
    "solar_plant_pack",
    "default_world_model_registry",
]
