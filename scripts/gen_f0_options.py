r"""M2-①: 从云笔数据(yunque_all.json)生成 F0 新建书向导选项字典。

来源: 可用\自家家具-桶0\云笔数据\yunque_all.json(创作选项字典节,任务书 §7 已盘实)。
产出: backend/app/f0_options.json —— 前端向导的单一数据源,不硬编码进组件。
裁剪原则(风险 4 防过度设计): 只取向导需要的组;金手指/情节模式原样保留供选,不引申。
"""
import json
import os

SRC = r"E:\大项目终极anget\可用\自家家具-桶0\云笔数据\yunque_all.json"
DST = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "f0_options.json")

src = json.load(open(SRC, encoding="utf-8"))
dic = src["创作选项字典"]

out = {
    "_source": "可用\\自家家具-桶0\\云笔数据\\yunque_all.json 创作选项字典(2026-08-30 提取)",
    "小说类型": dic["小说类型"],
    "核心设定流派": dic["创作字典"]["叙事套路"],  # 云笔"叙事套路"15 项 = 构建表单"核心设定/流派"
    "受众定位": dic["受众定位"],
    "风格偏好": dic["风格偏好"],
    "力量体系": dic["力量体系分类"],  # 五类各若干项,向导按类分组下拉
    "金手指类型": dic["金手指类型预设"],
    "情节结构模式": [
        {"value": x["value"], "label": x["label"], "desc": x["desc"]}
        for x in dic["情节结构模式"]
    ],
}

json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("written", DST)
for k, v in out.items():
    if not k.startswith("_"):
        print(f"  {k}: {len(v)} 项")
