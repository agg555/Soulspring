# 第三方代码来源与区分声明(THIRD-PARTY-NOTICES)

**本项目整体许可**:除本清单明确列出的第三方来源外,本仓库全部代码、文档与提示词资产
均为 Soulspring(思源)原创,以 **GNU Affero General Public License v3.0(AGPL-3.0)**
发布,完整许可证文本见 [LICENSE](LICENSE)。
Copyright (C) 2026 王泽(Soulspring 作者)。

本清单按来源区分「代码级移植」与「设计/结构参考」两类;边界以各文件头部标注为准。

---

## 一、inkflow(代码级移植,MIT License)

移植自 inkflow(`inkflow` —— AI 小说引擎,MIT License,
Copyright (c) 2026 ElysiaQWQ)。移植时对该项目快照(LICENSE 为 MIT)整体取得。

### 代码级移植(衍生文件,保留原版权与许可声明)

| 本仓库文件 | 上游来源 |
|---|---|
| `backend/app/audit/code_checks.py` | `inkflow/pipeline/audit/code_checks.py` |
| `backend/app/audit/anti_ai.py` | `inkflow/pipeline/anti_ai.py` |
| `backend/app/llm/client.py` | `inkflow/core/llm_client.py` |
| `backend/app/llm/atomic_io.py` | `inkflow/utils/atomic_io.py` |

以上文件均为 Python 重写/适配(接口对齐本项目结构),算法与核心逻辑随上游。

### 设计参考(实现为原创,非代码复制)

| 本仓库文件 | 参考内容 |
|---|---|
| `backend/app/audit/world_state.py` | 审计器所需 WorldState 的 JSON 形状契约对齐(适配层为本项目原创) |
| `backend/app/routers/l2.py` | Observer/Reflector 回写思路(定稿正文→真相文件 diff→人批准合并) |

MIT License 原文(适用于上述全部 inkflow 来源):

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

---

## 二、Chevoink / 启创墨域(代码级移植 + 结构契约参考)

上游:Chevoink(启创墨域),© 2026 Xcy8010(AI 全栈小说创作与阅读平台)。
**上游许可历史**:2026-08-30 快照时为 MIT License;其后上游将许可改为
GNU AGPL-3.0(见双方 2026-08-31 商业授权协议背景条款)。

### 代码级移植(衍生文件)

| 本仓库文件 | 上游来源 | 取得依据 |
|---|---|---|
| `backend/app/audit/humanity.py` | `api/lib/agent/humanity-quality.ts` 的 `analyzeDeterministicQuality`(commit `b301168` 快照,现留档于本地素材桶) | 移植当时(2026-08-31)上游为 **MIT License,Copyright (c) 2026 Xcy8010**;MIT 授权不可追溯撤销。本文件随本项目整体以 AGPL-3.0 发布(向上兼容) |

### 结构契约参考(实现为原创,非代码复制)

| 本仓库位置 | 参考内容 |
|---|---|
| `backend/app/db.py` | ChangeSet / AgentRun / AiUsageLog 三表结构裁剪(单用户化) |
| `backend/app/routers/workbench.py` | 变更集完整契约:patches 逐条 + validations 审计挂钩 + 乐观锁 |
| `backend/app/routers/task_runner.py` 等任务机制 | 后台任务流设计(见 `docs/备忘-chevoink技能与任务流深读-2026-08-31.md`) |

### 署名保留声明

依双方 2026-08-31 商业授权协议第三条,以下署名在本项目内**不得删除或篡改**:

> Chevoink(启创墨域),© 2026 Xcy8010

该协议文本由被授权方留存,不入本仓库;协议授予的闭源托管豁免仅覆盖 Chevoink
上游原始软件之权利,不改变本项目自身代码的 AGPL-3.0 义务。

---

## 三、运行时第三方依赖

后端 Python 依赖见 `backend/requirements.txt`,前端 npm 依赖见 `frontend/package.json`;
各依赖以其自身发布渠道随附的许可证为准,本项目未修改其源码。
