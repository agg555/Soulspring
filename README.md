# Soulspring(思源)

自用型 AI 小说写作系统——AI 出想法和草稿(发散),人主编(99% 人工把控)。
本地单用户 Web 应用:Python(FastAPI)后端 + React(Vite)前端,SQLite 单文件主存 + 章节正文 .md 镜像。

> 本仓库为发布副本:不含运行数据(`data\`)与内部规划文档(`docs\`)。

## 许可证

AGPL-3.0,全文见 [LICENSE](LICENSE)。
第三方代码来源与许可区分见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
(inkflow / Chevoink 的移植文件与结构参考逐文件对照,以及许可历史说明)。

## 架构一览

| 目录 | 内容 |
|---|---|
| `backend\` | FastAPI 服务:装配引擎 / 双层审计(代码层 + anti-AI)/ 写章工作台(后台任务化生成管道)/ 统一对话(会话 + 建议协议两档采纳)/ 统一图谱引擎 / 三栏书工作区(书级对话+实体互链)/ 书况台聚合 / 拆书 / 预算记账 |
| `frontend\` | React + Vite 薄前端(构建产物由后端静态托管) |
| `prompts\` | 提示词资产(技能 SKILL.md + 章节管道模板) |
| `scripts\` | 启动脚本(Windows) |

## 启动(Windows)

1. 双击 `scripts\启动.bat`:自动建 venv、装依赖、(首次)构建前端、拉起服务并打开浏览器;
2. 浏览器地址 `http://127.0.0.1:8600`,API key 首次在设置页写入(存 `data\secrets.local.json`,git 忽略)。

## 测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/ -q   # 60 全绿
```
