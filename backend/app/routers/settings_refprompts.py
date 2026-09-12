"""参考提示词库(2026-09-09 拍板:长文本生成触点可挂,仅作参考注入)。

(2026-09-10 自 settings_api.py 抽出,纯移动零行为变化——大工程②A:
库全量替换 + 绑定三层(全局/触点/书)全量替换,镜像 touches 语义;
子路由不带 prefix,settings_api include_router 叠加 /api/settings;
旧导入路径 RefPromptItem/ReferencePromptsIn/put_reference_prompts 由 settings_api re-export。)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..settings_store import get_settings, update_settings

refprompts_router = APIRouter(tags=["settings"])

PROMPT_ITEM_MAX = 50        # 库容上限
PROMPT_NAME_MAX = 30
PROMPT_TEXT_MAX = 10000     # 2026-09-10 用户拍板:2000 → 10000(长参考文也可入库)
BIND_IDS_MAX = 10           # 单层绑定上限(防拼爆 system)


class RefPromptItem(BaseModel):
    id: str
    name: str
    text: str


class ReferencePromptsIn(BaseModel):
    items: list[RefPromptItem]
    global_bind: list[str] | None = None
    actions: dict[str, list[str]] | None = None
    books: dict[str, list[str]] | None = None


def _clean_bind(ids: list[str]) -> list[str]:
    out: list[str] = []
    for i in ids:
        i = str(i).strip()
        if i and i not in out:
            out.append(i)
    if len(out) > BIND_IDS_MAX:
        raise HTTPException(422, f"单层绑定过多(上限 {BIND_IDS_MAX} 条)")
    return out


@refprompts_router.put("/reference-prompts")
def put_reference_prompts(body: ReferencePromptsIn) -> dict:
    """库全量替换+绑定三层全量替换(镜像 touches 语义);引用校验=绑定 id 必须在库。"""
    if len(body.items) > PROMPT_ITEM_MAX:
        raise HTTPException(422, f"提示词条目过多(上限 {PROMPT_ITEM_MAX} 条)")
    seen: set[str] = set()
    items_out: list[dict] = []
    for it in body.items:
        name = it.name.strip()
        text = it.text.strip()
        if not name:
            raise HTTPException(422, "提示词名称不能为空")
        if len(name) > PROMPT_NAME_MAX:
            raise HTTPException(422, f"名称过长(上限 {PROMPT_NAME_MAX} 字)")
        if not text:
            raise HTTPException(422, f"提示词「{name}」内容为空")
        if len(text) > PROMPT_TEXT_MAX:
            raise HTTPException(422, f"提示词「{name}」过长(上限 {PROMPT_TEXT_MAX} 字)")
        if it.id in seen:
            raise HTTPException(422, f"提示词 id 重复: {it.id}")
        seen.add(it.id)
        items_out.append({"id": it.id, "name": name, "text": text})
    known = seen
    patch: dict = {"items": items_out}
    if body.global_bind is not None:
        gb = _clean_bind(body.global_bind)
        for i in gb:
            if i not in known:
                raise HTTPException(422, f"全局绑定引用了不存在的提示词: {i}")
        patch["global_bind"] = gb
    if body.actions is not None:
        patch["actions"] = {}
        for a, ids in body.actions.items():
            clean = _clean_bind(ids)
            for i in clean:
                if i not in known:
                    raise HTTPException(422, f"触点 {a} 绑定引用了不存在的提示词: {i}")
            patch["actions"][a] = clean
    if body.books is not None:
        patch["books"] = {}
        for pid, ids in body.books.items():
            clean = _clean_bind(ids)
            for i in clean:
                if i not in known:
                    raise HTTPException(422, f"书 {pid} 绑定引用了不存在的提示词: {i}")
            patch["books"][pid] = clean
    update_settings("reference_prompts", patch)
    return {"ok": True, "reference_prompts": get_settings()["reference_prompts"]}
