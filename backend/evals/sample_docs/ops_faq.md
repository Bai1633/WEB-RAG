# 部署与运维 FAQ

## 容器编排

生产环境通过 Docker Compose 一共启动 6 个服务：postgres（pgvector 镜像）、redis、backend（gunicorn + uvicorn worker）、worker（Celery）、frontend（React 静态资源）、nginx（统一入口）。nginx 监听 80 与 443 端口，backend 与 frontend 只在内网暴露。

## 端口约定

- PostgreSQL：5432
- Redis：6379
- Nginx 对外：80 / 443

## Windows 开发环境

Celery 在 Windows 下默认的 prefork 进程池不可用，本系统在 Windows 上自动切换为 solo 池，在进程内执行任务；生产 Linux 环境仍使用 prefork 并发池。

## 数据备份

每日使用 `pg_dump` 备份 PostgreSQL；上传的原始文件与向量表数据分别位于 uploads 卷与数据库中，恢复时需同时还原。
