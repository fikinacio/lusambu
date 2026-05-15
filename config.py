from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ANTHROPIC_API_KEY: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    EVOLUTION_API_URL: str
    EVOLUTION_API_KEY: str
    EVOLUTION_INSTANCE: str
    FIDEL_WHATSAPP_NUMBER: str
    CHECKPOINT_DB_PATH: str = "/data/checkpoints.sqlite"


settings = Settings()
