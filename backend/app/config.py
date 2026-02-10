from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = Field(..., alias="MONGO_URI")
    mongo_db: str = Field("withyou", alias="MONGO_DB")

    apns_team_id: Optional[str] = Field(None, alias="APNS_TEAM_ID")
    apns_key_id: Optional[str] = Field(None, alias="APNS_KEY_ID")
    apns_auth_key_path: Optional[str] = Field(None, alias="APNS_AUTH_KEY_PATH")
    apns_topic: Optional[str] = Field(None, alias="APNS_TOPIC")
    apns_use_sandbox: bool = Field(True, alias="APNS_USE_SANDBOX")

    scheduler_interval_seconds: int = Field(60, alias="SCHEDULER_INTERVAL_SECONDS")

    api_key: Optional[str] = Field(None, alias="API_KEY")

settings = Settings()

