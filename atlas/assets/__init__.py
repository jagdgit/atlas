"""Asset Store subsystem (Phase 0 · ATLAS_OS_ROADMAP §5.9, P8).

Raw, versioned source artifacts (repos, PDFs, DWG/CAD, MATLAB, images) — the things
knowledge is *extracted from*, stored through the Storage Manager. Assets ≠ Knowledge:
keeping them separate makes re-parsing (e.g. a better CAD reader) cheap.
"""

from __future__ import annotations

from atlas.assets.repository import AssetRepository
from atlas.assets.service import AssetError, AssetStore

__all__ = ["AssetStore", "AssetRepository", "AssetError"]
