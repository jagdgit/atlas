"""Derived Artifact Store — re-export from ``atlas.artifacts`` (OI-C1 back-compat).

The physical home is now ``atlas.artifacts.store``. Import from either path.
"""

from atlas.artifacts.store import ARTIFACT_SCOPE, DerivedArtifactStore, artifact_key

__all__ = ["ARTIFACT_SCOPE", "DerivedArtifactStore", "artifact_key"]
