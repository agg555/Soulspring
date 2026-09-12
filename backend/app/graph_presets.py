"""预设题材包(批次七⑥:模板双层·预设层)。

题材包=一套板组合+节点组+清单模板,一键铺进当前书,降新建书空白成本。
payload 形状与用户模板完全一致(nodes/edges 临时下标),套用走同一条
templates.apply 管道——预设与用户模板同协议,行为零分叉。
AI 起草模板内容不设直写通道:一律走对话建议协议(graph_add 批准闸门),
与本路由的人操作端点分离(执行书④判据"AI 起草走闸门"由架构保证)。
"""
from __future__ import annotations

# 清单卡条目速写:字符串 → {"text": t, "done": False}
def _cl(*items: str) -> dict:
    return {"card": "checklist", "items": [{"text": t, "done": False} for t in items]}


def _node(label: str, x: int, y: int, sub: str = "", style: dict | None = None) -> dict:
    return {"label": label, "sub_label": sub, "x": x, "y": y, "style": style or {}}


PRESET_PACKS: dict[str, dict] = {
    "urban": {
        "name": "都市",
        "description": "都市异能/商战/重生:人物+势力+主控板(金手指/钩子/卷检查单)",
        "boards": [
            {"name": "都市人物", "kind": "character", "nodes": [
                _node("主角", 80, 80, "身世+金手指补全后移入档案"),
                _node("女主/搭档", 280, 80, "与主角的关系张力"),
                _node("对手", 80, 260, "反派动机线"),
                _node("导师/贵人", 280, 260, "资源与代价"),
            ], "edges": [
                {"from": 0, "to": 1, "label": "并肩", "kind": "同盟"},
                {"from": 0, "to": 2, "label": "对立", "kind": "克制"},
            ]},
            {"name": "势力版图", "kind": "faction", "nodes": [
                _node("主角方阵营", 80, 100),
                _node("既得利益方", 300, 100),
                _node("地下秩序", 190, 280),
            ], "edges": [
                {"from": 0, "to": 1, "label": "利益冲突", "kind": "克制"},
                {"from": 2, "to": 1, "label": "暗中渗透", "kind": "从属"},
            ]},
            {"name": "都市主控板", "kind": "free", "nodes": [
                _node("金手指设定", 60, 60, "规则/限制/代价三件套"),
                _node("主线钩子", 280, 60, "开篇 3 章必埋"),
                _node("卷检查单", 60, 280, style=_cl(
                    "主线推进了吗", "伏笔埋/收对齐", "时间线不冲突",
                    "人物言行一致", "字数达标", "开头/结尾钩子")),
            ]},
        ],
    },
    "xuanhuan": {
        "name": "玄幻",
        "description": "东方玄幻/修真:人物+力量体系+地图(境界清单)",
        "boards": [
            {"name": "玄幻人物", "kind": "character", "nodes": [
                _node("主角", 80, 80, "资质/机缘/心魔"),
                _node("道侣/挚友", 280, 80),
                _node("宿敌", 80, 260, "境界压制关系"),
                _node("宗门长老", 280, 260),
            ], "edges": [
                {"from": 0, "to": 3, "label": "师承/提携", "kind": "从属"},
                {"from": 0, "to": 2, "label": "夺机缘", "kind": "因果"},
            ]},
            {"name": "力量体系", "kind": "power", "nodes": [
                _node("炼气", 60, 60), _node("筑基", 260, 60),
                _node("金丹", 460, 60), _node("元婴", 660, 60),
                _node("境界检查单", 60, 260, style=_cl(
                    "新境界的能力边界写清了吗", "越级战的代价合理吗",
                    "功法/丹药命名统一", "境界与剧情节点对齐")),
            ], "edges": [
                {"from": 0, "to": 1, "label": "突破", "kind": "承接"},
                {"from": 1, "to": 2, "label": "突破", "kind": "承接"},
                {"from": 2, "to": 3, "label": "突破", "kind": "承接"},
            ]},
            {"name": "山河地图", "kind": "map", "nodes": [
                _node("起点村/城", 80, 200),
                _node("宗门", 300, 100),
                _node("秘境", 300, 300, "中期主线舞台"),
                _node("上界入口", 540, 200, "后期悬念"),
            ], "edges": [
                {"from": 0, "to": 1, "label": "入山道", "kind": "通道"},
                {"from": 1, "to": 2, "label": "秘境入口", "kind": "通道"},
                {"from": 2, "to": 3, "label": "飞升路", "kind": "去向"},
            ]},
        ],
    },
    "systemflow": {
        "name": "系统流",
        "description": "系统/签到/无限流:人物+道具+系统设定板(规则清单/任务模板)",
        "boards": [
            {"name": "系统流人物", "kind": "character", "nodes": [
                _node("宿主", 80, 100, "系统绑定方式"),
                _node("关键配角", 300, 100, "任务相关人"),
                _node("系统化身/幕后", 190, 280, "可选:系统人格化"),
            ], "edges": [
                {"from": 1, "to": 0, "label": "任务目标", "kind": "因果"},
            ]},
            {"name": "道具流转", "kind": "item", "nodes": [
                _node("新手礼包", 60, 60),
                _node("关键道具", 280, 60, "章节锚点道具"),
                _node("限制器/代价物", 60, 260),
            ], "edges": [
                {"from": 0, "to": 1, "label": "升级路线", "kind": "承接"},
            ]},
            {"name": "系统设定板", "kind": "system", "nodes": [
                _node("系统规则清单", 60, 60, style=_cl(
                    "奖励与惩罚写明", "升级节奏表", "隐藏规则/底层目的",
                    "系统不能做什么(边界)", "与主线绑定方式")),
                _node("任务模板", 300, 60, style=_cl(
                    "任务目标", "时限/惩罚", "奖励结算", "失败分支")),
                _node("面板字段", 60, 280, "属性/积分/商城等展示字段"),
            ]},
        ],
    },
}
