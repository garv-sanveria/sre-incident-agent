from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    groq_api_key: str = ""
    primary_model: str = "openai/gpt-oss-120b"
    fallback_model: str = "qwen/qwen3.8-27b"
    hindsight_base_url: str = "http://localhost:8888"
    hindsight_api_key: str = ""
    bank_id: str = "sre-incidents"
    remote_memory: bool = False
    api_token: str = ""
    demo_enabled: bool = True
    data_dir: Path = Path("data")
    fixtures_dir: Path = Path("fixtures")
    reranker_floor: float = Field(default=0.35, ge=0, le=1)
    final_floor: float = Field(default=0.65, ge=0, le=1)
    max_tool_calls: int = Field(default=12, ge=2, le=12)
    request_timeout: float = Field(default=8, gt=0, le=60)
    retry_limit: int = Field(default=3, ge=1, le=5)
    max_backoff: float = Field(default=5, ge=0, le=30)
