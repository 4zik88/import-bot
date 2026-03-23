from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    admin_user_id: int
    admin_user_ids: str = ""
    database_path: str = "data/bot.db"

    # Persistent settings (survive redeploy via env vars)
    roapp_api_token: str = ""
    channel_id: str = ""
    warehouse_id: str = ""
    auto_import_enabled: str = ""
    auto_import_interval: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def all_admin_ids(self) -> set[int]:
        ids = {self.admin_user_id}
        for part in self.admin_user_ids.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
        return ids

    @property
    def db_path(self) -> Path:
        p = Path(self.database_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()  # type: ignore[call-arg]
