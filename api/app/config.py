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
    rag_top_k: int = 5

    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
