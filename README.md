# Web RAG 知识库问答系统

> 私有化可部署的 RAG 知识库问答系统：三通道混合检索 + 交叉编码器重排 + 拒答门控 + 引用溯源，前后端分离，支持 Docker 一键部署。

[![CI](https://github.com/Bai1633/WEB-RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/Bai1633/WEB-RAG/actions/workflows/ci.yml)

## 简介

一个面向私有知识库的检索增强生成（RAG）问答系统。用户注册登录后创建知识库、上传文档（PDF / Word / Markdown / HTML / TXT / CSV），系统在后台完成解析、分块与向量化；提问时走 **三通道混合检索 → RRF 融合 → 交叉编码器重排 → 拒答门控** 链路，返回流式回答并附引用来源。

## 核心特性

- **三通道混合检索**：向量检索（`pgvector`）+ 中文全文检索（PostgreSQL `tsvector`，对中文做逐字切分）+ 词法相似（`pg_trgm` `word_similarity`），三路并行召回后 RRF 融合。
- **交叉编码器重排**：BGE `bge-reranker-v2-m3` 对候选精排，提升顶部相关性。
- **拒答门控**：召回为空时明确拒答，避免无依据作答。
- **多轮查询改写**：结合对话历史改写检索 query。
- **异步文档管道**：上传后由 Celery worker 完成解析 / 分块 / 向量化，状态可追踪。
- **认证与权限**：JWT + argon2 密码哈希；三级 RBAC（owner / editor / viewer）；登录失败锁定。
- **可观测性**：`structlog` 结构化日志 + Prometheus `/metrics`。
- **检索评测闭环**：内置离线评测脚本（`backend/evals`）。
- **前端体验**：SSE 流式回答、引用溯源卡片、数据看板、拖拽上传、代码高亮。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI · LlamaIndex 0.12 · SQLAlchemy 2 (async) · asyncpg · Alembic |
| 存储 | PostgreSQL 16 + pgvector · Redis 7 |
| 异步任务 | Celery 5（worker + beat）· Redis broker |
| 检索 | pgvector · tsvector(中文) · pg_trgm · RRF · bge-reranker-v2-m3 |
| 认证 | JWT（python-jose）· argon2 |
| 观测 | structlog · prometheus-client |
| 前端 | React 18 · TypeScript · Vite · Tailwind CSS · zustand · react-router |
| 模型 | 默认阿里云百炼 DashScope（`qwen3.7-flash` / `qwen3.7-text-embedding`），走 OpenAI 兼容模式；亦支持 OpenAI 官方 / Ollama / 本地 HuggingFace |
| 部署 | Docker Compose（nginx + 前端 + 后端 + worker + PostgreSQL + Redis） |

## 检索链路

```
query ─┬─► 向量检索 (pgvector)       ─┐
       ├─► 全文检索 (tsvector / 中文) ─┼─► RRF 融合 ─► BGE 重排 ─► 拒答门控 ─► LLM 生成 (SSE)
       └─► 词法检索 (pg_trgm)         ─┘
```

## 目录结构

```
web_rag/
├─ backend/            FastAPI 服务、检索引擎、Celery 任务、Alembic 迁移、评测
├─ frontend/           React + TypeScript 前端（Vite）
├─ deploy/             生产部署：docker-compose（6 服务）+ nginx 配置
├─ docker-compose.yml  本地开发基础设施（PostgreSQL + Redis）
├─ init.sql            数据库初始化（启用 vector 扩展）
└─ 项目运行指南.md      本地运行详细手册
```

## 快速开始（本地开发）

### 0. 前置

- Docker Desktop
- Python 3.11+
- Node.js 18+

### 1. 启动基础设施（PostgreSQL + Redis）

```bash
docker compose up -d
```

### 2. 后端

```bash
cd backend
cp .env.example .env          # Windows: copy .env.example .env
# 编辑 .env，填写 LLM_API_KEY / EMBEDDING_API_KEY（默认走 DashScope）
python -m venv venv
# Windows: venv\Scripts\activate     macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head          # 建表
uvicorn app.main:app --port 8000 --reload
```

- 健康检查：`http://localhost:8000/api/health`
- 就绪探针：`http://localhost:8000/api/ready`（探查 DB 与 Redis）
- 接口文档：`http://localhost:8000/docs`

### 3. Celery（异步文档处理，务必启动）

```bash
# worker（新终端）
cd backend
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# beat（新终端，定时清理卡住任务 / 过期 token）
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

> 不起 worker，上传的文档会一直停在 `processing`，问答也检索不到内容。

### 4. 前端

```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

### Windows 提示

后端连接 Docker 中的 PostgreSQL / Redis 时，连接串请用 `127.0.0.1` 而非 `localhost`（`localhost` 可能被解析为 IPv6 `::1`，导致连不上）。

## Docker 部署（生产）

```bash
cd deploy
cp .env.example .env          # 必填 JWT_SECRET_KEY、LLM / Embedding key、CORS_ORIGINS
docker compose up -d --build
# 浏览器访问 http://<服务器地址>
```

> `deploy/.env.example` 内含各变量的用途与安全提醒。

## 环境变量

关键变量（完整见 `backend/.env.example` / `deploy/.env.example`）：

| 变量 | 说明 |
| --- | --- |
| `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_BASE_URL` | 对话模型 |
| `EMBEDDING_API_KEY` / `EMBEDDING_MODEL_NAME` / `EMBEDDING_BASE_URL` | 向量模型 |
| `EMBEDDING_DIM` | **必须**与 embedding 模型输出维度一致（`qwen3.7-text-embedding` = 1024） |
| `JWT_SECRET_KEY` | 认证密钥（生产必须改为随机长串） |
| `DB_*` / `REDIS_URL` | 数据库 / Redis 连接 |
| `CORS_ORIGINS` | 允许的浏览器来源（用 IP 访问就写 IP） |
| `RERANK_ENABLED` | 是否启用本地重排模型 |

## 安全说明

- `.env` 已在 `.gitignore` 中，**切勿提交真实密钥**。
- 生产环境请务必重新生成 `JWT_SECRET_KEY`、修改数据库密码，并按实际访问地址设置 `CORS_ORIGINS`。

## 相关文档

- [`项目运行指南.md`](./项目运行指南.md) — 本地运行详细步骤
- `backend/evals/README.md` — 检索评测说明

## License

本项目暂未声明开源许可证。
