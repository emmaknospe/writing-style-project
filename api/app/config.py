from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-5"

    # Four slashes: sqlite+aiosqlite:/// + the absolute path /data/app.db, which
    # is the named volume mounted into the api container by docker-compose.yml.
    app_database_url: str = "sqlite+aiosqlite:////data/app.db"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection_name: str = "writing_style"
    qdrant_vector_size: int = 1536

    google_cloud_project: str
    google_cloud_location: str = "us-central1"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Corpus chunks per search_corpus call. Higher than a chat turn would need:
    # a brief sweeps several themes, so each individual query is narrower.
    # Default for the source-picker search endpoint (routers/search.py), which
    # backs a human scanning hits one screen at a time.
    rag_top_k: int = 5

    # Corpus chunks per search_corpus call. Higher than the picker's default:
    # a brief sweeps several themes, so each individual query is narrower.
    brief_top_k: int = 8

    # Hard cap on Anthropic server-side web searches per brief. Each search is
    # billed on top of tokens ($10/1,000), so this bounds the per-brief cost.
    web_search_max_uses: int = 5

    # Output ceiling for a brief. pydantic-ai defaults to 4096, which truncates
    # a multi-point brief mid-JSON -- the response then fails schema validation
    # with fields simply missing, which reads like a model error rather than a
    # length one. pydantic-ai switches to streaming transparently above the
    # non-streaming HTTP-timeout threshold, so a high value is safe here.
    max_output_tokens: int = 16000

    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
