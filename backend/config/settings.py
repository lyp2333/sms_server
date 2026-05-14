import os
import secrets
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 基本配置
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/sms_database.db")
    api_key: Optional[str] = os.getenv("API_KEY", None)
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8322"))
    log_level: str = os.getenv("LOG_LEVEL", "info").lower()

    # 数据库配置
    db_connect_args: Dict[str, Any] = {"check_same_thread": False}

    # 应用配置
    app_title: str = "SMS 验证码接收服务"
    app_version: str = "1.0"

    # Session 签名密钥（必须写入 .env 持久化，否则重启后 Cookie 失效）
    secret_key: str = os.getenv("SECRET_KEY", secrets.token_hex(32))

    # 卡密配置
    card_key_length: int = 8
    # 排除易混淆字符 O/0、I/1
    card_key_charset: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    # 限速配置
    rate_limit_window: int = 60       # 滑动窗口秒数
    rate_limit_max_fails: int = 5     # 窗口内最大失败次数
    rate_limit_lockout: int = 300     # 锁定时长（秒）
    
    @property
    def requires_api_key(self) -> bool:
        """检查是否需要API密钥验证"""
        return self.api_key is not None and self.api_key.strip() != ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# 创建一个全局可用的设置实例
settings = Settings()
