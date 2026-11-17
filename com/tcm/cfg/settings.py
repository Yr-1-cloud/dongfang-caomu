"""全局配置：统一从项目根 .env 读取，别在各模块里散落 os.getenv。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根：com/tcm/cfg/settings.py -> parents[3] = zhongyishizhan/
BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env")


class Settings:
    # ---- MySQL ----
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "tcm")
    DB_CHARSET: str = os.getenv("DB_CHARSET", "utf8mb4")

    # ---- 连接池 ----
    DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "20"))
    DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "2"))

    # ---- 向量库 / 模型 ----
    CHROMA_DIR: str = str(BASE_DIR / os.getenv("CHROMA_DIR", "chroma_db"))
    EMBED_MODEL_PATH: str = str(BASE_DIR / os.getenv(
        "EMBED_MODEL_PATH", "models/BAAI--bge-large-zh-v1.5/snapshots/master"))

    # ---- DeepSeek ----
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL_CHAT: str = os.getenv("DEEPSEEK_MODEL_CHAT", "deepseek-chat")


settings = Settings()
