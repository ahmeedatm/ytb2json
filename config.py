from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openai_api_key: str
    api_secret_key: str
    proxy_url: str = ""
    # Timeouts en secondes. En production avec proxy, l'extraction prend ~2-4s.
    # En local sans proxy, YouTube peut être lent : augmenter si besoin.
    extract_timeout: float = 15.0
    llm_timeout: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
