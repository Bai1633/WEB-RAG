"""Application configuration management via pydantic-settings."""

from functools import lru_cache

import structlog
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

logger = structlog.get_logger()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    environment: str = "dev"
    log_level: str = "info"

    # Database - individual components (URL built from these)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "web_rag"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_pool_size: int = 50

    # JWT Auth
    jwt_secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    # 登录失败锁定：窗口期内连续失败 N 次后锁定账号（Redis 计数，fail-open）
    login_max_attempts: int = 5
    login_lockout_window_seconds: int = 900

    # LLM
    llm_provider: str = "compatible"
    llm_model_name: str = "qwen-turbo"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048

    # Embedding
    embedding_provider: str = "openai"
    embedding_model_name: str = "text-embedding-ada-002"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_dim: int = 1536
    embedding_batch_size: int = 32

    # RAG
    chunk_size: int = 512
    chunk_overlap: int = 50
    similarity_top_k: int = 10
    # 混合检索：向量检索 + PostgreSQL trigram 词法检索，RRF 融合
    hybrid_search_enabled: bool = True
    # 词法渠道（trigram 相似度）各取前 N 个候选，再与向量结果 RRF 融合
    lexical_top_k: int = 15
    # 全文渠道（tsvector）取前 N 个候选
    fulltext_top_k: int = 15
    # RRF 融合常数：score = Σ w_i / (k + rank)
    rrf_k: int = 60
    # 融合后保留的 topN（通常与 similarity_top_k 一致或略大）
    rrf_top_k: int = 10
    # trigram 相似度下限，低于该值的 chunk 视为无关（也用于走 GIN 索引加速）
    trgm_similarity_threshold: float = 0.1
    # 各检索通道在 RRF 融合中的权重（可按数据分布调优）
    vector_weight: float = 1.0
    lexical_weight: float = 1.0
    fulltext_weight: float = 1.0
    # 查询最小有效长度（去除空白与标点后），过短则跳过词法/全文通道
    hybrid_min_query_length: int = 2
    rerank_top_n: int = 5
    rerank_model_name: str = "bge-reranker-v2-m3"
    # 本地重排模型路径（相对 backend 目录即可）；若路径不存在会自动 fallback 按相似度排序。
    rerank_model_path: str = "./models/bge-reranker-v2-m3"
    # 重排开关：true=启用 BGE 重排；false=仅按相似度排序（省内存/无需 GPU）。
    rerank_enabled: bool = True
    confidence_threshold: float = 0.35
    # 注入 LLM 的上下文最大 token 数（防止超长上下文超出模型窗口或稀释注意力）
    context_max_tokens: int = 3000
    # 模型上下文窗口大小（用于 token 预算计算，history+context+system 不超过此值）
    model_max_context: int = 8192
    # 系统提示词（RAG 引擎答问规则）。留空则使用内置默认提示词。
    system_prompt: str = ""
    # 多轮对话历史轮数（每次 chat 将最近 N 轮历史发送给 LLM）
    chat_history_rounds: int = 5
    # 多轮查询改写：有历史时先用 LLM 把追问改写成独立完整的问题再去检索，
    # 解决"它多少钱？"这类指代问题直接拿原句做向量检索召回收敛的缺陷。
    # 生成仍使用用户原句；失败自动回退原句。关闭可省一次 LLM 调用。
    query_rewrite_enabled: bool = True
    # 文档处理超时（秒），超时后 cleanup_stuck_documents 会重新入队
    document_processing_timeout: int = 3600

    # Upload
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50
    allowed_mime_types: str = (
        "application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "text/markdown,text/html,text/plain,text/csv"
    )

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Trust X-Forwarded-For for client IP extraction (rate limiting / logs).
    # Only enable when the app is behind a trusted reverse proxy (e.g. the
    # bundled nginx); otherwise clients can spoof the header to rotate keys.
    trust_proxy_headers: bool = False

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_worker_concurrency: int = 4
    celery_task_soft_time_limit: int = 3600
    celery_task_time_limit: int = 3900

    # Derived properties
    @property
    def database_url(self) -> str:
        """Build async database URL using SQLAlchemy URL object."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)

    @property
    def database_url_sync(self) -> str:
        """Build sync database URL (for Celery, Alembic offline mode, etc.)."""
        return URL.create(
            drivername="postgresql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins string into list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_mime_types_list(self) -> list[str]:
        """Parse allowed MIME types string into list."""
        return [mt.strip() for mt in self.allowed_mime_types.split(",") if mt.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "dev"

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Validate that critical settings are changed from defaults in production."""
        if self.environment not in ("dev", "prod", "test", "staging"):
            raise ValueError(f"Invalid environment: {self.environment}. Must be one of: dev, prod, test, staging")

        if self.is_production:
            warnings: list[str] = []

            if self.jwt_secret_key == "change-me-in-production-please-use-a-long-random-string":
                warnings.append("JWT_SECRET_KEY is still the default value")

            if not self.llm_api_key and self.llm_provider in ("openai", "ollama"):
                warnings.append(f"LLM_API_KEY is not set but provider is {self.llm_provider}")

            if not self.embedding_api_key and self.embedding_provider in ("openai",):
                warnings.append(f"EMBEDDING_API_KEY is not set but provider is {self.embedding_provider}")

            if self.cors_origins == "http://localhost:3000,http://localhost:5173":
                warnings.append("CORS_ORIGINS still uses default localhost values")

            if warnings:
                for w in warnings:
                    logger.warning("production_config_warning", message=w)

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
