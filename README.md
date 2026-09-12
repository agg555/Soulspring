<div align="center">

# Soulspring(思源)

**本地单用户 AI 小说写作系统 —— AI 出想法和草稿,人主编每一个决定。**

*一辆辅助驾驶,不是自动驾驶。*

[![CI](https://github.com/agg555/Soulspring/actions/workflows/ci.yml/badge.svg)](https://github.com/agg555/Soulspring/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-Vite%20%2B%20TS-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/Storage-SQLite%20%2B%20.md%20镜像-003B57?logo=sqlite&logoColor=white)

</div>

---

## 它解决什么问题

长篇连载最难缠的是两件**状态问题**:

- **延续性** —— 死掉的角色不再出场、资源不凭空出现、伏笔不烂尾;
- **统一性** —— 设定不崩、人物不走形、信息边界不穿帮。

Soulspring 用四层数据模型(L1 档案 / L2 世界状态 / L3 大纲 / L4 正文)+ 三道协议
(写入 / 装配 / 检查)把它们交给工程化兜底;去 AI 味与可看性这类审美问题,则
**机器铺路、人裁决** —— 写章工作台出草稿,审稿对话走人工终审,朱雀检测自用把关。

## 设计三铁律

1. **AI 永不直写** —— AI 产出一律走"建议 → 人批准"闸门:字段 diff 确认、正文进
   变更集、建节点先出预览;每次落库留 `human_gate` 审计痕。没有例外入口。
2. **类型不丢** —— 章状态机(五态+打回+解封)/场景五字段/卷章挂载规则是骨架,
   任何新功能不动它们;子题(topic)纯轻节点。
3. **零配置零破坏** —— 新开关默认 = 原行为;老书升级无感(迁移只加列/加表)。

## 核心特性

**三栏书工作区**
- 左栏:大纲树(WPS 式大纲级别 + topic 子题无限嵌套 + 目录模式 + 悬浮预览 +
  算法体检)/ 档案库(世界观·角色·力量·势力·地理·物品经济六类,树形嵌套)/
  构思树(待议→采纳→放弃三态,放弃即冻结不喂 AI)
- 中栏:对话台(书级多线会话 / 填空式模板 / @引用 / 💡参考提示词 / 思考档直选)
  ↔ 写章工作台(计划卡→草稿→规整→审计→评审五阶段 / 版本链红绿对比 / 人改 /
  AI 自修 / 章节信息卡)
- 右栏:图谱中心(十类板统一引擎)/ 书况台(成本·质量分·戏份曲线·节奏谱)/
  剧情时间线 / L2 看板 / 复习卡(时间线+伏笔速览)/ 拆书官

**写章管道**:装配预算裁剪(6000 字上下文)→ 计划卡 → 草稿 → 规整 → 代码层审计
→ LLM 评审,全程后台任务化 + 步骤时间线实时可见;版本链追加式(v1..vN),可回滚。

**AI 闸门与触点控制**
- 全部 AI 触点统一登记(TOUCHES):每个动作可配追加提示词 / 模型覆盖 / 输出上限;
- 生效链:本书×触点 > 本书默认 > 触点覆盖 > 全局默认 > 出厂登记;
- 参考提示词库三层绑定(全局/触点/按书),长文本生成五入口全生效;
- 回包三级解析兜底(宽松 → strict=False → 抽取),空回包可读提示。

**统一图谱引擎**:人物关系 / 剧情事件 / 道具 / 地点 / 势力 / 伏笔流转(状态泳道)/
力量体系 / 世界观 / 自由画布(文本卡·清单卡·实体链接卡三卡型)+ 全书总览聚合;
网格吸附 / 锚点连线 / 派生成链 / 图例过滤 / 千章级 LOD(2022 节点远景 17ms)。

**算法优先,离线免费**:六项规则体检常驻(断头章 / 孤立卷 / 伏笔未回收 / 重名 /
时间冲突 / 章密度)+ 去 AI 味结构规则库(rules-as-data 可热更)+ 违禁审查——
**没配 API key 也能用到 95 分,AI 是增强层不是前提**。

**工程配套**
- 每日自动备份(服务运行即快照,保留 14 份)+ 设置页一键快照 / 推送备份仓;
- 书 = 目录镜像:正文分卷 + 设定 + 大纲 + 时间线实时镜像为 `.md`(DB 唯一真源);
- 顶栏全文搜索(FTS5 trigram,千章毫秒级);
- 成本记账:逐次落库(模型 / token / 缓存命中 / 峰谷价),单章成本可查、超线告警;
- 导出 txt / md;阅读模式;命名工坊;帮助页。

## 架构一览

| 目录 | 内容 |
|---|---|
| `backend\` | FastAPI 服务:装配引擎 / 双层审计(代码层规则 + anti-AI)/ 写章管道(任务化+步骤时间线)/ 统一对话(建议协议+两档采纳)/ 统一图谱引擎 / 书况台聚合 / 拆书 / 记账 / 每日备份守护 |
| `frontend\` | React + Vite + TypeScript 薄前端(零 UI 库,设计令牌 CSS 变量;构建产物由后端静态托管) |
| `prompts\` | 提示词资产(技能 SKILL.md + 章节管道模板)——修改即改行为,不硬编码 |
| `scripts\` | 启动脚本(Windows:直启 / 看门狗守护) |
| `.github\` | CI:pytest 181 + tsc/build + Playwright e2e 冒烟五景 |

**技术栈**:Python 3.14 · FastAPI · SQLite(WAL,自建 `user_version` 迁移 v22)·
React 19 · TypeScript · Vite · 原生 JS 封装 OpenAI SDK 客户端 · FTS5 trigram。

## 快速开始(Windows)

1. 双击 **`scripts\启动-看门狗.bat`**(推荐,进程退出自动退避拉起);
   或 `scripts\启动.bat`(自动建 venv、装依赖、首次构建前端、拉起服务并开浏览器);
2. 浏览器打开 `http://127.0.0.1:8600`;
3. 设置页写入 API key(存 `data\secrets.local.json`,git 忽略)——**BYOK**:
   内置 GLM / DeepSeek 预设,任意 OpenAI 兼容接口均可接入;不配 key 也能用全部
   算法功能。

<details>
<summary>手动启动(非 Windows / 开发者)</summary>

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # 运行依赖
.venv/Scripts/pip install -r requirements-dev.txt    # 测试依赖(pytest)
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8600

cd ../frontend
npm ci && npm run build    # 构建产物由后端静态托管
```

</details>

## 测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests -q      # 181 用例全绿
cd ../frontend
npx playwright test                               # e2e 冒烟五景(需本地已有书)
```

CI(push 触发):backend pytest + frontend tsc/build + e2e 冒烟(空库自动跳过)。

> 本仓库只含项目本体;运行数据(`data\`)与内部工程过程文档不在仓库内。

## 许可证

[AGPL-3.0](LICENSE)。第三方代码来源与许可区分见
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)(inkflow / Chevoink 的移植文件
与结构参考逐文件对照,以及许可历史说明)。

---

<div align="center">

*为中文网文作者打造 · 本地优先 · 你的数据永远在你自己的磁盘上*

</div>
