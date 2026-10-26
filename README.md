# 智能旅行推荐与行程规划

面向旅游场景的检索增强生成（RAG）知识库系统，支持景点攻略、线路推荐、酒店信息、美食推荐、交通指南的内容导入、检索与带引用的知识问答。

## 技术栈

- 后端：Python 3.11+ / FastAPI / SQLAlchemy / MySQL
- RAG：本地 bge-base-zh-v1.5 向量化 + numpy 向量索引 + 余弦检索
- LLM：DeepSeek（OpenAI 兼容），支持流式输出
- 联网搜索：Tavily（知识库无结果时兜底）
- 前端：Vue 3 + Element Plus（见 frontend/）

## 智能行程

前端「智能行程」页接收城市、1–7 天、总预算和偏好。模型可在最多 6 轮、8 次工具调用内选择景点、线路、住宿、美食、交通检索及确定性预算计算；工具参数经校验，跨城市检索会被拒绝。结果包含逐日安排、费用估算、精选的知识库引用和可查看的执行轨迹。工具只读，不会预订或修改外部数据。

每日行程还包含结构化地点。设置 `AMAP_WEB_KEY`（高德开放平台 Web 服务 API Key）后，系统用地点搜索核验名称与城市，并对相邻地点查询步行或公交耗时。单段超过 90 分钟、每日游览加交通超过 9 小时时，模型有一次自动调整机会；最终仍有问题会明确显示。未配置 Key、地点匹配失败或路线接口失败时，界面标记为“未核验”，不将缺失耗时当作零。营业时间只显示高德返回的当日信息，因用户未提供出行日期，不据此保证实际开放。最多核验 21 个地点，接口调用会消耗高德配额。

智能行程支持多轮对话：生成初版后，可以问“为什么这样安排？”获取基于当前版本的解释，也可以输入“第二天少走路”“预算降到 1200 元”生成新版。修改时系统先更新用户明确改变的约束，再参考上一版重跑检索、预算与地图核验；成功后保存新版本及变更摘要，旧版本和提问记录可在页面查看。刷新页面会恢复最近打开的行程，历史会话存放于 `storage/plan_sessions/`。失败的追问不会覆盖上一个成功版本，过期版本提交会返回 409。

本地资料目前覆盖 6 个示例目的地。规划其他城市时，各检索工具先查本地索引；无相关片段时使用 Tavily 联网搜索，并在结果中标明网页来源和核实提醒。未配置 `TAVILY_API_KEY` 或搜索没有可靠结果时，系统明确提示资料不足。普通问答先识别问题中的目的地，再按地区检索；未命中时使用相同的联网搜索兜底。联网搜索结果只用于当前回答，不自动导入知识库，也不保证价格或营业时间实时准确。

```
用户要求 → DeepSeek 选择工具 → 知识库检索 / 预算计算 → 参数与结果校验 → 行程 + 引用 + 轨迹
```

- `POST /api/v1/agent/plan`：请求示例 `{"city":"杭州","days":2,"budget":1500,"interests":"自然风景"}`。
- `GET/POST /api/v1/agent/sessions`：列出行程会话或根据上述请求创建初版。
- `GET /api/v1/agent/sessions/{session_id}`：读取完整版本历史。
- `DELETE /api/v1/agent/sessions/{session_id}`：删除本地行程会话及其版本。
- `POST /api/v1/agent/sessions/{session_id}/messages`：追问修改，请求示例 `{"message":"第二天少走路","base_version":1}`。
- `GET /api/v1/agent/runs/{run_id}`：读取成功或失败的工具轨迹、耗时和 Token 用量；轨迹保存在 `storage/agent_runs/`。
- `GET /ready`：核对 MySQL 片段数和本地索引数。不一致时返回 503，可运行 `python -m scripts.rebuild_index` 修复。

### 可重复评测

```bash
# 12 个检索样本，不调用在线模型
python -m scripts.evaluate_retrieval

# 旅行规划样本；每个样本会调用 DeepSeek 并产生费用，先跑 3 个即可
python -m scripts.evaluate_agent --limit 3
```

评测结果保存在 `storage/evals/`，包含逐题结果、任务完成率、城市与天数约束、引用、预算、结构化地点覆盖、地图核验率、路段覆盖、耗时和 Token。地图核验率只有在配置有效高德 Key 时才有意义。样本目前来自项目自带的 6 个目的地文档，不能代表真实用户流量；投递简历前可继续补充困难问题和人工评分。

当前本机基线（2026-10-23）：12 个检索样本 hit@1 为 12/12；12 个规划样本结构化完成 12/12、引用非空 12/12、未超预算 12/12，平均耗时 9.74 秒、平均总用量 15,184 Token。基线逐题数据见 `evals/agent-baseline-20261023.json`。曾尝试缩短工具返回的片段，在同组样本的一次运行中得到 11/12、平均 14,452 Token，因此恢复原配置；对照数据见 `evals/agent-short-context-20261023.json`。这些自动指标尚未核验行程事实准确性和引用是否真正支持每项建议，不应当作答案准确率。

地图升级后的单样本联调（杭州 2 天，2026-10-23）完成率、结构化地点覆盖率、地图核验率和路段覆盖率均为 1.0，见 `evals/agent-map-smoke-20261023.json`。这只是一次端到端冒烟测试，不代表跨城市成功率；路线耗时来自高德接口，仍需出行前核实实时交通和开放情况。

## 本机运行

```bash
# 在包含 pyproject.toml 的目录执行
# 1. 使用 Python 3.11+ 创建虚拟环境并安装依赖
python -m venv .venv
# Windows: .venv\Scripts\activate；macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

# 2. 配置环境变量（复制 .env.example 为 .env，填入密钥和可用的 MySQL 连接信息）
cp .env.example .env

# 3. 确认 MySQL 已启动，再启动服务（启动时自动预热模型 + 建表）
uvicorn app.main:app --reload
```

首次运行前，在 MySQL 中创建 `travel_kb` 数据库，并在 `.env` 填写有权限连接它的账号。`EMBEDDING_MODEL_PATH` 留空时，首次启动会按 `EMBEDDING_MODEL` 下载模型；如果已有本地模型，可将它设为本机模型目录。服务启动后，在另一个终端运行前端：

```bash
cd frontend
npm ci
npm run dev
```

访问 http://localhost:5173。首次使用知识库前，回到项目根目录运行 `python -m scripts.import_all` 导入示例资料。模型下载、DeepSeek、Tavily 和高德接口需要网络；联网搜索与地图核验所需的 Key 可在 `.env` 中按需配置。不要将 `.env`、模型文件或 `storage/` 提交到公开仓库。

若在 `.env` 设置 `APP_API_KEY`，所有 `/api/v1/` 请求都需要 `X-API-Key` 请求头。前端右上角的 **API Key** 按钮可输入密钥，密钥仅保存在当前浏览器会话中；留空则保持本机免鉴权模式。问答检索默认过滤相似度低于 `RETRIEVE_MIN_SCORE` 的片段；无有效片段且设置了 `TAVILY_API_KEY` 时，使用联网搜索兜底。阈值可根据实际问答效果调整。

PyCharm 中请使用本目录的 `.venv/Scripts/python.exe` 作为解释器；从外层文件夹打开项目时，运行配置的工作目录应设为本目录（包含 `.env` 和 `pyproject.toml` 的文件夹）。

启动后访问 http://localhost:8000/docs 查看接口文档。

## 导入知识库

```bash
# 批量导入 data/ 目录下全部文档
python -m scripts.import_all
```

若数据库与本地向量索引因异常中断而不一致，可先备份 `storage/vector_index.npz`，再运行 `python -m scripts.rebuild_index` 从数据库片段重建索引。

## 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/import | 上传文档导入 |
| GET  | /api/v1/import/tasks/{id} | 导入任务状态 |
| GET  | /api/v1/search/attractions | 景点检索 |
| GET  | /api/v1/search/routes | 线路检索 |
| GET  | /api/v1/search/info | 实用信息（hotel/food/transport） |
| POST | /api/v1/chat | 问答（非流式） |
| POST | /api/v1/chat/stream | 问答（SSE 流式） |
| GET/POST/DELETE | /api/v1/sessions | 会话管理 |

## 运行测试

```bash
python -m pytest tests/ -v
```

真实导入检索测试需要 MySQL 与本地 Embedding 模型；MySQL 未就绪时该测试会跳过。其余测试不访问外部服务。

> 说明：Windows 下 torch（Embedding 模型）与 pymysql 存在原生库冲突，应用启动时会先预热模型再建表，规避段错误。向量库采用 numpy 本地索引（数据量级下暴力余弦检索毫秒级），替代 chromadb 以规避其在 Windows 下的稳定性问题。
