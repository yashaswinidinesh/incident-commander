from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://ic:ic_secret@localhost:5432/incident_cmd"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-change-in-prod"
    OPENAI_API_KEY: str = ""
    DEFAULT_MODEL: str = "gpt-4o-mini"
    class Config: env_file = ".env"
settings = Settings()
