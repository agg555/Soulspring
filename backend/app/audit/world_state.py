"""L2 真相文件的轻量运行时视图。

代码层审计(移植自 inkflow)需要 WorldState 形态的数据;本模块把 our L2
l2_files 表(七类真相文件,JSON content)适配成审计器所需接口。
JSON 形状约定(与 inkflow world_state.py 对齐,字段裁剪):

- character_matrix: {"characters": {名: {"status": "alive|dead|missing|unknown",
                       "description": "", "traits": ""}},
                     "info_boundaries": {名: {"known_facts": ["..."]}}}
- resource_ledger:  {"entries": {键: {"name": "", "owner": "", "status": "held|lost|consumed|destroyed"}}}
- pending_hooks:    {"foreshadowing": [{"detail": "", "planted_chapter": 1, "status": "pending|resolved|invalid"}]}
- subplot_board:    {"subplots": [{"name": "", "last_advanced": 1, "status": "active|resolved|shelved"}]}
- current_state / chapter_summaries / emotional_arcs: 自由 JSON(审计暂不消费)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..db import tx

L2_TYPES = [
    "current_state", "resource_ledger", "pending_hooks", "chapter_summaries",
    "subplot_board", "emotional_arcs", "character_matrix",
]


@dataclass
class CharacterLite:
    name: str
    status: str = "alive"
    description: str = ""
    traits: str = ""


@dataclass
class ResourceLite:
    key: str
    name: str
    owner: str = ""
    status: str = "held"


@dataclass
class ForeshadowingLite:
    detail: str
    planted_chapter: int = 0
    status: str = "pending"


@dataclass
class BoundaryLite:
    known_facts: list = field(default_factory=list)


@dataclass
class SubplotLite:
    name: str
    last_advanced: int = 0
    status: str = "active"


class ResourceLedgerLite:
    def __init__(self, entries: dict[str, ResourceLite]):
        self.entries = entries


class CharacterMatrixLite:
    def __init__(self, info_boundaries: dict[str, BoundaryLite]):
        self.info_boundaries = info_boundaries


class SubplotBoardLite:
    def __init__(self, subplots: list[SubplotLite]):
        self.subplots = subplots

    def get_stalled(self, stall_threshold: int, current_chapter: int) -> list[SubplotLite]:
        return [s for s in self.subplots
                if s.status == "active" and current_chapter - s.last_advanced >= stall_threshold]


class WorldStateLite:
    """审计器所需的最小 WorldState 视图;由 l2_files JSON 构建。"""

    def __init__(
        self,
        characters: dict[str, CharacterLite],
        resource_ledger: ResourceLedgerLite,
        foreshadowing_pool: list[ForeshadowingLite],
        character_matrix: CharacterMatrixLite,
        subplot_board: SubplotBoardLite,
        raw: dict[str, Any],
    ):
        self.characters = characters
        self.resource_ledger = resource_ledger
        self.foreshadowing_pool = foreshadowing_pool
        self.character_matrix = character_matrix
        self.subplot_board = subplot_board
        self.raw = raw

    def get_stale_foreshadowing(self, max_age: int, current_chapter: int) -> list[ForeshadowingLite]:
        return [f for f in self.foreshadowing_pool
                if f.status == "pending" and current_chapter - f.planted_chapter >= max_age]


def _parse_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def load_world_state(project_id: str) -> WorldStateLite:
    """从 l2_files 表构建审计视图(缺文件按空处理,不报错)。"""
    with tx() as conn:
        rows = conn.execute(
            "SELECT file_type, content FROM l2_files WHERE project_id=? AND status='official'",
            (project_id,)).fetchall()
    blobs = {r["file_type"]: _parse_json(r["content"]) for r in rows}

    characters = {
        name: CharacterLite(name=name, status=str(v.get("status", "alive")),
                            description=str(v.get("description", "")),
                            traits=str(v.get("traits", "")))
        for name, v in blobs.get("character_matrix", {}).get("characters", {}).items()
        if isinstance(v, dict)
    }
    info_boundaries = {
        name: BoundaryLite(known_facts=[str(f) for f in v.get("known_facts", [])])
        for name, v in blobs.get("character_matrix", {}).get("info_boundaries", {}).items()
        if isinstance(v, dict)
    }
    resource_entries = {
        key: ResourceLite(key=key, name=str(v.get("name", key)),
                          owner=str(v.get("owner", "")), status=str(v.get("status", "held")))
        for key, v in blobs.get("resource_ledger", {}).get("entries", {}).items()
        if isinstance(v, dict)
    }
    foreshadowing_pool = [
        ForeshadowingLite(detail=str(f.get("detail", "")),
                          planted_chapter=int(f.get("planted_chapter", 0)),
                          status=str(f.get("status", "pending")))
        for f in blobs.get("pending_hooks", {}).get("foreshadowing", [])
        if isinstance(f, dict)
    ]
    subplots = [
        SubplotLite(name=str(s.get("name", "")), last_advanced=int(s.get("last_advanced", 0)),
                    status=str(s.get("status", "active")))
        for s in blobs.get("subplot_board", {}).get("subplots", [])
        if isinstance(s, dict)
    ]

    return WorldStateLite(
        characters=characters,
        resource_ledger=ResourceLedgerLite(resource_entries),
        foreshadowing_pool=foreshadowing_pool,
        character_matrix=CharacterMatrixLite(info_boundaries),
        subplot_board=SubplotBoardLite(subplots),
        raw=blobs,
    )
