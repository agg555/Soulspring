"""WPS 式大纲 AI 点子入口(任务词 2026-09-09 阶段 3)。

红线:AI 永不直写 outline_nodes。两个入口都只产出"建议",落库唯一路径 =
subtopics/adopt(人批准闸门,与对话建议 subtopic_add 同一道落地函数)。
- 子题拆分:AI 读节点上下文(含 body),出子题树 JSON;前端闸门窗人可增删改,
  批准后由 adopt_subtopic_tree 落 topic 轻节点;
- 正文建议:AI 对节点 body 出改写文本;前端 diff 确认(轻档)后走 PUT outline 写回。
触点登记:outline_subtopic_split(8000)/ outline_body_suggest(4000),批次六机制现成。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now, _prompt
from ..assembly import build_node_context
from ..db import tx
from ..ledger.usage import chat_completion
from ..settings_store import ref_prompt_section, touch_prompt_append
from .adopt import adopt_subtopic_tree, sanitize_subtopic_tree
from .generation import _parse_json_loose

router = APIRouter(prefix="/api/outline", tags=["outline-ai"])


def _load_node(nid: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
    if row is None:
        raise HTTPException(404, "节点不存在")
    return dict(row)


class AiHintIn(BaseModel):
    hint: str = ""   # 作者的追加要求(可空)
    # 参考提示词运行时手选(2026-09-09;None=走绑定链:书>触点>全局)
    ref_prompt_ids: list[str] | None = None


@router.post("/{nid}/ai/subtopic-split")
def subtopic_split(nid: str, body: AiHintIn | None = None) -> dict:
    """AI 子题拆分:产出子题树建议(不落库);前端闸门窗人可增删改后批准。"""
    node = _load_node(nid)
    context = build_node_context(node["project_id"], nid)
    hint = (body.hint or "").strip() if body else ""
    system = _prompt("大纲-子题拆分.md", {
        "NODE_CONTEXT": context,
        "USER_HINT": hint or "(无,自由发挥)",
    })
    system += ref_prompt_section("outline_subtopic_split", node["project_id"],
                                 body.ref_prompt_ids if body else None)
    system += touch_prompt_append("outline_subtopic_split")
    try:
        result = chat_completion(
            [{"role": "system", "content": system},
             {"role": "user", "content": "请严格按系统指令输出 JSON。"}],
            action="outline_subtopic_split", agent_type="planner",
            project_id=node["project_id"],
            input_summary=f"子题拆分:{node['title'][:40]}")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"模型调用失败:{exc}")
    try:
        data = _parse_json_loose(result["content"])
    except ValueError as exc:
        raise HTTPException(502, f"模型输出不是合法 JSON({exc});可重试")
    tree = sanitize_subtopic_tree(data.get("tree") if isinstance(data, dict) else None)
    if not tree:
        raise HTTPException(502, "模型未产出有效子题树;可重试或调整追加要求")
    return {"tree": tree, "usage": result["usage"], "run_id": result["run_id"],
            "cost": result["usage"]["cost_total"]}


@router.post("/{nid}/ai/body-suggest")
def body_suggest(nid: str, body: AiHintIn | None = None) -> dict:
    """AI 正文建议:对节点 body 出改写文本(不落库);前端 diff 确认后轻档写回。"""
    node = _load_node(nid)
    context = build_node_context(node["project_id"], nid)
    hint = (body.hint or "").strip() if body else ""
    system = _prompt("大纲-正文建议.md", {
        "NODE_CONTEXT": context,
        "USER_HINT": hint or "(无,按你的判断改写)",
    })
    system += ref_prompt_section("outline_body_suggest", node["project_id"],
                                 body.ref_prompt_ids if body else None)
    system += touch_prompt_append("outline_body_suggest")
    try:
        result = chat_completion(
            [{"role": "system", "content": system},
             {"role": "user", "content": "请严格按系统指令输出改写后的完整正文。"}],
            action="outline_body_suggest", agent_type="planner",
            project_id=node["project_id"],
            input_summary=f"正文建议:{node['title'][:40]}")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"模型调用失败:{exc}")
    return {"text": result["content"].strip(), "usage": result["usage"],
            "run_id": result["run_id"], "cost": result["usage"]["cost_total"]}


class SubtopicAdoptIn(BaseModel):
    tree: list   # 人改过的子题树 [{title, children?: [...]}]


@router.post("/{nid}/subtopics/adopt", status_code=201)
def adopt_subtopics(nid: str, body: SubtopicAdoptIn) -> dict:
    """闸门批准落库(人点确认才到这):子题树落 topic 轻节点,留 human_gate 痕。"""
    result = adopt_subtopic_tree(nid, body.tree)
    return {"ok": True, **result, "decided_at": _now()}
