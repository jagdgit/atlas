"""Repository for the Code store (S19, D11/§5d): ``learning.repositories`` +
``learning.patterns``.

The only SQL layer for Engineering Intelligence. Learned repositories are created /
deactivated through the S18b learning ledger (via a sink), so this layer just
persists structure. Generalized patterns are a materialised view recomputed by
``IntelligenceService.generalize`` and stored here for fast recall.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.learning import EngineeringPattern, LearnedRepository
from atlas.repositories.base import BaseRepository

_REPO_COLS = (
    "id, name, root, languages, frameworks, entry_points, dependencies, file_count, "
    "symbol_count, loc, summary, top_symbols, patterns, policy, status, repo_uid, "
    "root_commit, normalized_remote, asset_id, asset_version, created_at, updated_at"
)
_PAT_COLS = (
    "id, name, category, description, prevalence, repo_count, total_repos, confidence, "
    "level, evidence, status, created_at, updated_at"
)


class IntelligenceRepository(BaseRepository):
    # --- learned repositories (L2) --------------------------------------
    def add_repository(
        self,
        *,
        name: str,
        root: str,
        languages: dict[str, int] | None = None,
        frameworks: list[str] | None = None,
        entry_points: list[str] | None = None,
        dependencies: dict[str, list[str]] | None = None,
        file_count: int = 0,
        symbol_count: int = 0,
        loc: int = 0,
        summary: str = "",
        top_symbols: list[Any] | None = None,
        patterns: list[Any] | None = None,
        policy: str = "project",
        repo_uid: str | None = None,
        root_commit: str | None = None,
        normalized_remote: str | None = None,
        asset_id: str | None = None,
        asset_version: int | None = None,
    ) -> LearnedRepository:
        # Re-learning a repository replaces its previous active row (idempotent learn).
        # Identity is the stable repo_uid (BB12) when known — so re-cloning the same repo to
        # a different path still supersedes the right row — else the filesystem root.
        if repo_uid:
            self.execute(
                "UPDATE learning.repositories SET status = 'reverted', updated_at = now() "
                "WHERE repo_uid = %s AND status = 'active'",
                (repo_uid,),
            )
        else:
            self.execute(
                "UPDATE learning.repositories SET status = 'reverted', updated_at = now() "
                "WHERE root = %s AND status = 'active'",
                (root,),
            )
        row = self.fetch_one(
            f"""
            INSERT INTO learning.repositories
                (name, root, languages, frameworks, entry_points, dependencies,
                 file_count, symbol_count, loc, summary, top_symbols, patterns, policy,
                 repo_uid, root_commit, normalized_remote, asset_id, asset_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            RETURNING {_REPO_COLS}
            """,
            (
                name, root, Jsonb(languages or {}), Jsonb(frameworks or []),
                Jsonb(entry_points or []), Jsonb(dependencies or {}), file_count,
                symbol_count, loc, summary, Jsonb(top_symbols or []),
                Jsonb(patterns or []), policy,
                repo_uid, root_commit, normalized_remote, asset_id, asset_version,
            ),
        )
        return LearnedRepository.from_row(row)

    def get_repository(self, repo_id: UUID | str) -> LearnedRepository | None:
        row = self.fetch_one(
            f"SELECT {_REPO_COLS} FROM learning.repositories WHERE id = %s",
            (str(repo_id),),
        )
        return LearnedRepository.from_row(row) if row else None

    def get_by_repo_uid(self, repo_uid: str) -> LearnedRepository | None:
        """The active learned repository for a stable ``repo_uid`` (BB12), newest first."""
        row = self.fetch_one(
            f"SELECT {_REPO_COLS} FROM learning.repositories "
            f"WHERE repo_uid = %s AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (str(repo_uid),),
        )
        return LearnedRepository.from_row(row) if row else None

    def list_repositories(self, *, limit: int = 100) -> list[LearnedRepository]:
        rows = self.fetch_all(
            f"SELECT {_REPO_COLS} FROM learning.repositories "
            f"WHERE status = 'active' ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return LearnedRepository.from_rows(rows)

    def search_repositories(self, query: str, *, limit: int = 20) -> list[LearnedRepository]:
        like = f"%{query.strip()}%"
        rows = self.fetch_all(
            f"""
            SELECT {_REPO_COLS} FROM learning.repositories
            WHERE status = 'active'
              AND (name ILIKE %s OR root ILIKE %s OR summary ILIKE %s
                   OR frameworks::text ILIKE %s OR languages::text ILIKE %s)
            ORDER BY created_at DESC LIMIT %s
            """,
            (like, like, like, like, like, limit),
        )
        return LearnedRepository.from_rows(rows)

    def set_repository_status(self, repo_id: UUID | str, status: str) -> bool:
        return (
            self.execute(
                "UPDATE learning.repositories SET status = %s, updated_at = now() "
                "WHERE id = %s",
                (status, str(repo_id)),
            )
            > 0
        )

    def count_repositories(self) -> int:
        return (
            self.fetch_val(
                "SELECT count(*) FROM learning.repositories WHERE status = 'active'"
            )
            or 0
        )

    # --- generalized patterns (L4) --------------------------------------
    def replace_patterns(self, patterns: list[dict[str, Any]]) -> int:
        """Retire the current generalized set and insert the freshly computed one."""
        self.execute(
            "UPDATE learning.patterns SET status = 'reverted', updated_at = now() "
            "WHERE status = 'active'"
        )
        for p in patterns:
            self.execute(
                """
                INSERT INTO learning.patterns
                    (name, category, description, prevalence, repo_count, total_repos,
                     confidence, level, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    p.get("name", ""), p.get("category", "engineering"),
                    p.get("description", ""), float(p.get("prevalence", 0.0)),
                    int(p.get("repo_count", 0)), int(p.get("total_repos", 0)),
                    float(p.get("confidence", 0.0)), int(p.get("level", 4)),
                    Jsonb(p.get("evidence", [])),
                ),
            )
        return len(patterns)

    def list_patterns(self, *, limit: int = 100) -> list[EngineeringPattern]:
        rows = self.fetch_all(
            f"SELECT {_PAT_COLS} FROM learning.patterns "
            f"WHERE status = 'active' ORDER BY prevalence DESC LIMIT %s",
            (limit,),
        )
        return EngineeringPattern.from_rows(rows)

    def count_patterns(self) -> int:
        return (
            self.fetch_val(
                "SELECT count(*) FROM learning.patterns WHERE status = 'active'"
            )
            or 0
        )
