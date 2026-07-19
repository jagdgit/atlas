"""Asset Store tests (Phase 0 · ATLAS_OS_ROADMAP §5.9, P8).

Hermetic: a real :class:`StorageManager` runs over the in-memory fake storage repo
(reused from the storage tests), and the DB-backed ``AssetRepository`` is replaced with
an in-memory fake. This exercises the Assets↔Storage seam (versioning, checksum
verification, re-fetch coordinates) without a live Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.assets import AssetError, AssetStore
from atlas.storage import StorageManager
from tests.test_storage import FakeStorageRepo


class FakeAssetRepo:
    def __init__(self) -> None:
        self.assets: list[dict[str, Any]] = []
        self.versions: list[dict[str, Any]] = []
        self.groups: list[dict[str, Any]] = []
        self.members: list[dict[str, Any]] = []
        self._aid = 0
        self._vid = 0
        self._gid = 0

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return next((a for a in self.assets if str(a["id"]) == str(asset_id)), None)

    def get_by_natural(self, kind: str, name: str) -> dict[str, Any] | None:
        return next(
            (a for a in self.assets if a["kind"] == kind and a["name"] == name), None
        )

    def create_asset(self, **kw: Any) -> dict[str, Any]:
        self._aid += 1
        row = {"id": self._aid, "current_version": 0, **kw}
        self.assets.append(row)
        return row

    def set_current_version(self, asset_id: str, version: int) -> dict[str, Any] | None:
        a = self.get_asset(asset_id)
        if a:
            a["current_version"] = version
        return a

    def next_version(self, asset_id: str) -> int:
        vs = [v["version"] for v in self.versions if str(v["asset_id"]) == str(asset_id)]
        return (max(vs) + 1) if vs else 1

    def add_version(self, **kw: Any) -> dict[str, Any]:
        self._vid += 1
        row = {"id": self._vid, **kw}
        self.versions.append(row)
        return row

    def get_version(self, asset_id: str, version: int | None = None) -> dict[str, Any] | None:
        vs = [v for v in self.versions if str(v["asset_id"]) == str(asset_id)]
        if version is not None:
            vs = [v for v in vs if v["version"] == version]
        return max(vs, key=lambda v: v["version"]) if vs else None

    def list_versions(self, asset_id: str) -> list[dict[str, Any]]:
        return [v for v in self.versions if str(v["asset_id"]) == str(asset_id)]

    def list_assets(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            return list(self.assets)
        return [a for a in self.assets if a["kind"] == kind]

    # --- groups ---------------------------------------------------------
    def create_group(self, *, kind, name, metadata=None):
        existing = self.get_group_by_natural(kind, name)
        if existing is not None:
            return existing
        self._gid += 1
        row = {"id": f"group-{self._gid}", "kind": kind, "name": name,
               "metadata": metadata or {}}
        self.groups.append(row)
        return row

    def get_group(self, group_id):
        return next((g for g in self.groups if str(g["id"]) == str(group_id)), None)

    def get_group_by_natural(self, kind, name):
        return next(
            (g for g in self.groups if g["kind"] == kind and g["name"] == name), None
        )

    def list_groups(self, kind=None):
        if kind is None:
            return list(self.groups)
        return [g for g in self.groups if g["kind"] == kind]

    def add_member(self, *, group_id, asset_id, role=None, metadata=None):
        for m in self.members:
            if str(m["group_id"]) == str(group_id) and str(m["asset_id"]) == str(asset_id):
                m["role"], m["metadata"] = role, metadata or {}
                return m
        row = {"group_id": group_id, "asset_id": asset_id, "role": role,
               "metadata": metadata or {}}
        self.members.append(row)
        return row

    def remove_member(self, group_id, asset_id):
        before = len(self.members)
        self.members = [
            m for m in self.members
            if not (str(m["group_id"]) == str(group_id)
                    and str(m["asset_id"]) == str(asset_id))
        ]
        return len(self.members) < before

    def list_members(self, group_id):
        out = []
        for m in self.members:
            if str(m["group_id"]) == str(group_id):
                asset = self.get_asset(m["asset_id"])
                if asset:
                    out.append({**asset, "member_role": m["role"],
                                "member_metadata": m["metadata"]})
        return out

    def list_groups_for_asset(self, asset_id):
        out = []
        for m in self.members:
            if str(m["asset_id"]) == str(asset_id):
                group = self.get_group(m["group_id"])
                if group:
                    out.append({**group, "member_role": m["role"]})
        return out


@pytest.fixture()
def store(tmp_path):
    storage = StorageManager(tmp_path / "storage", FakeStorageRepo())
    return AssetStore(storage, FakeAssetRepo())


def test_register_creates_asset_and_version(store):
    out = store.register("pdf", "paper.pdf", b"%PDF-1.7 ...", source_uri="https://x/y")
    assert out["asset"]["kind"] == "pdf"
    assert out["asset"]["current_version"] == 1
    assert out["version"]["version"] == 1
    assert out["version"]["size_bytes"] == len(b"%PDF-1.7 ...")


def test_get_bytes_roundtrip(store):
    out = store.register("image", "logo.png", b"\x89PNG\r\n")
    asset_id = out["asset"]["id"]
    assert store.get_bytes(asset_id) == b"\x89PNG\r\n"


def test_reregister_bumps_version_and_keeps_history(store):
    a = store.register("pdf", "paper.pdf", b"draft-1")["asset"]
    asset_id = a["id"]
    out2 = store.register("pdf", "paper.pdf", b"draft-2")
    assert out2["version"]["version"] == 2
    assert out2["asset"]["current_version"] == 2
    # both versions are independently retrievable
    assert store.get_bytes(asset_id) == b"draft-2"
    assert store.get_bytes(asset_id, version=1) == b"draft-1"
    assert len(store.versions(asset_id)) == 2


def test_same_name_different_kind_are_distinct_assets(store):
    p = store.register("pdf", "spec", b"pdf-bytes")["asset"]
    d = store.register("dwg", "spec", b"dwg-bytes")["asset"]
    assert p["id"] != d["id"]
    assert store.get_bytes(p["id"]) == b"pdf-bytes"
    assert store.get_bytes(d["id"]) == b"dwg-bytes"


def test_checksum_mirrors_stored_blob(store):
    import hashlib

    out = store.register("pdf", "p", b"payload")
    assert out["version"]["checksum"] == hashlib.sha256(b"payload").hexdigest()


def test_verify_true_then_false_on_corruption(store):
    out = store.register("pdf", "p", b"trusted")
    asset_id = out["asset"]["id"]
    assert store.verify(asset_id) is True
    store.path_of(asset_id).write_bytes(b"tampered")
    assert store.verify(asset_id) is False
    with pytest.raises(store_error_type()):
        store.get_bytes(asset_id)


def test_get_bytes_unknown_asset_raises(store):
    with pytest.raises(AssetError):
        store.get_bytes("does-not-exist")


def test_list_assets_by_kind(store):
    store.register("pdf", "a", b"1")
    store.register("pdf", "b", b"2")
    store.register("dwg", "c", b"3")
    assert len(store.list_assets("pdf")) == 2
    assert len(store.list_assets()) == 3


def test_register_from_path(store, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"disk-bytes")
    out = store.register("pdf", "fromdisk", src)
    assert store.get_bytes(out["asset"]["id"]) == b"disk-bytes"


def test_create_group_is_get_or_create(store):
    g1 = store.create_group("project", "atlas", metadata={"topic": "ingestion"})
    g2 = store.create_group("project", "atlas")
    assert g1["id"] == g2["id"]  # same natural key → same group
    assert store.get_group_by_name("project", "atlas")["id"] == g1["id"]


def test_group_membership_and_reverse_lookup(store):
    repo = store.register("git_repo", "atlas-repo", b"repo-bytes")["asset"]
    doc = store.register("document", "design-doc", b"doc-bytes")["asset"]
    group = store.create_group("project", "atlas")

    store.add_to_group(group["id"], repo["id"], role="code")
    store.add_to_group(group["id"], doc["id"], role="design")

    members = store.group_members(group["id"])
    assert {m["id"] for m in members} == {repo["id"], doc["id"]}
    assert {m["member_role"] for m in members} == {"code", "design"}

    # The reverse lookup: which groups is this asset in?
    groups = store.groups_for_asset(repo["id"])
    assert [g["id"] for g in groups] == [group["id"]]


def test_add_to_group_is_idempotent_and_updates_role(store):
    a = store.register("document", "d", b"x")["asset"]
    g = store.create_group("topic", "t")
    store.add_to_group(g["id"], a["id"], role="reference")
    store.add_to_group(g["id"], a["id"], role="primary")  # re-add updates role
    members = store.group_members(g["id"])
    assert len(members) == 1 and members[0]["member_role"] == "primary"


def test_remove_from_group(store):
    a = store.register("document", "d2", b"y")["asset"]
    g = store.create_group("topic", "t2")
    store.add_to_group(g["id"], a["id"])
    assert store.remove_from_group(g["id"], a["id"]) is True
    assert store.group_members(g["id"]) == []


def test_add_to_group_validates_group_and_asset(store):
    a = store.register("document", "d3", b"z")["asset"]
    g = store.create_group("topic", "t3")
    with pytest.raises(AssetError):
        store.add_to_group("no-such-group", a["id"])
    with pytest.raises(AssetError):
        store.add_to_group(g["id"], "no-such-asset")


def test_health_ok(store):
    assert store.health_check().healthy is True


def store_error_type():
    from atlas.storage import StorageError

    return StorageError
