"""Live-DB smoke for asset groups / relationships (Phase C · §C.2, migration 0029).

Wires the real Asset Store + Storage Manager against PostgreSQL to prove the group schema and
its joins hold: assets can be grouped, the group is queryable both ways, membership is idempotent,
and grouping is relationship (not ownership) — removing a member leaves the assets intact. Skipped
when PostgreSQL is unreachable (matches the other e2e modules).
"""

from __future__ import annotations

import uuid

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager


@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_group_relates_assets_both_ways_live(db, tmp_path):
    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))

    token = uuid.uuid4().hex
    repo = assets.register("git_repo", f"atlas-{token}", b"repo-bytes")["asset"]
    doc = assets.register("document", f"design-{token}", b"doc-bytes")["asset"]
    chat = assets.register("document", f"chat-{token}", b"chat-bytes")["asset"]

    group = assets.create_group("project", f"atlas-{token}", metadata={"topic": "ingestion"})
    assert assets.get_group_by_name("project", f"atlas-{token}")["id"] == group["id"]
    # Get-or-create: same natural key returns the same group.
    assert assets.create_group("project", f"atlas-{token}")["id"] == group["id"]

    assets.add_to_group(group["id"], repo["id"], role="code")
    assets.add_to_group(group["id"], doc["id"], role="design")
    assets.add_to_group(group["id"], chat["id"], role="transcript")

    members = assets.group_members(group["id"])
    assert {str(m["id"]) for m in members} == {str(repo["id"]), str(doc["id"]), str(chat["id"])}
    assert {m["member_role"] for m in members} == {"code", "design", "transcript"}

    # Reverse lookup + idempotent re-add (role update).
    groups = assets.groups_for_asset(repo["id"])
    assert str(group["id"]) in {str(g["id"]) for g in groups}
    assets.add_to_group(group["id"], repo["id"], role="primary")
    roles = {str(m["id"]): m["member_role"] for m in assets.group_members(group["id"])}
    assert roles[str(repo["id"])] == "primary"

    # Grouping is relationship, not ownership: removing a member keeps the asset.
    assert assets.remove_from_group(group["id"], chat["id"]) is True
    assert str(chat["id"]) not in {str(m["id"]) for m in assets.group_members(group["id"])}
    assert assets.get(str(chat["id"])) is not None
    assert assets.get_bytes(str(chat["id"])) == b"chat-bytes"
