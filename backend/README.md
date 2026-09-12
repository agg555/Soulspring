# backend/

FastAPI 服务(薄核)。任务书 §3:本地 Web、SQLite 单文件主存、零 token 代码层审计的地基从这里起。

## 运行

```
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8600 --app-dir backend
```

(一般不必手动跑——双击 `scripts\启动.bat`。)

## 模块地图

| 模块 | 职责 | 上游 |
|---|---|---|
| `app/db.py` | SQLite 连接 + 四层/日志建表迁移(版本步进,现 v2) | 任务书 §4 |
| `app/settings_store.py` | 设置 KV(DB,热生效)+ api_key 专用 secrets 文件 | F15 |
| `app/llm/client.py` | LLM 客户端(OpenAI 兼容 + extra 扩展参数透传),移植自 inkflow | F16,MIT |
| `app/llm/atomic_io.py` | 原子写,移植自 inkflow | F16,MIT |
| `app/ledger/usage.py` | AgentRun + AiUsageLog 记账管道(统一对话入口 chat_completion),结构取自 chevoink | F13/F14,MIT |
| `app/f0_options.json` | F0 向导选项字典(gen_f0_options.py 从云笔数据生成) | F0 |
| `app/l1_schema.json` | L1 六类条目字段定义(v1 裁剪件) | F1 |
| `app/routers/overview.py` | 总览:项目列表 + 成本卡片 + 建书 | F13/M2 |
| `app/routers/books.py` | 书籍详情/编辑 + 字典/schema 只读接口 | F0/M2 |
| `app/routers/l1.py` | L1 六类 + 提案批准流;风格指纹代码层拒写 | F1/写入协议 |
| `app/routers/outline.py` | 大纲树四级 + 五态状态机 + 时间戳日志 | F3/KPI |
| `app/routers/build.py` | AI 一键构建(仅手动触发,产出入提案区) | F2 |
| `app/routers/settings_api.py` | 设置页 API(模型/价格/预算/装配占位/key) | F15 |
| `app/routers/chat.py` | 测试对话(连通性验证) | M1 |
| `app/routers/usage_api.py` | 日志查看器(AiUsageLog/AgentRun 只读) | F14 |

## 纪律

- 提示词一律进 `prompts\`,不硬编码(执行计划书 §8 红线);
- api_key 只存 `data/secrets.local.json`(git 忽略),DB 与日志永不落 key;
- 写入协议(任务书 §4.2):AI 只写草稿区——后续模块接入时越权写入在代码层拒绝,不靠提示词。
