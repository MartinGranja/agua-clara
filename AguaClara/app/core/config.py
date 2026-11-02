from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    gemini_api_key: str = ''
    llm_model_name: str = 'gemini-3.6-flash'
    llm_timeout_seconds: int = 30
    # Visión híbrida: lecturas independientes por foto (1 a 3; 1 ahorra cuota de Gemini) y detector de color de respaldo.
    vision_samples: int = 2
    cv_enabled: bool = True
    database_url: str = 'sqlite:///./data/aguaclara.db'
    admin_token: str = ''
    allow_remote: bool = False
    # Aviso al dueño cuando entra una consulta (todos opcionales; se puede usar más de un canal).
    owner_whatsapp_phone: str = ''      # con código de país, ej. 5493515551234 (CallMeBot)
    callmebot_api_key: str = ''
    telegram_bot_token: str = ''
    telegram_chat_id: str = ''
    notify_webhook_url: str = ''

settings = Settings()
