import os
import secrets
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings


def _ensure_secret_key(env_path: str = ".env") -> str:
    """
    读取 .env 中的 SECRET_KEY；
    若不存在则生成一个随机密钥并追加写入 .env，保证重启后复用。
    """
    # 优先使用已有的环境变量（systemd EnvironmentFile 已注入）
    key = os.getenv("SECRET_KEY", "").strip()
    if key:
        return key

    # 尝试从 .env 文件解析
    abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../", env_path)
    abs_path = os.path.normpath(abs_path)
    if os.path.isfile(abs_path):
        with open(abs_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SECRET_KEY="):
                    key = line[len("SECRET_KEY="):].strip()
                    if key:
                        print(f"SECRET_KEY found in .env, using existing key: {key}")
                        return key

    # 首次启动：生成新密钥并写入 .env
    key = secrets.token_hex(32)
    with open(abs_path, "a", encoding="utf-8") as f:
        f.write(f"\n# Session 签名密钥（自动生成，请勿删除）\nSECRET_KEY={key}\n")
    return key


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

    # Session 签名密钥（首次启动自动生成并写入 .env，后续复用）
    secret_key: str = _ensure_secret_key()

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
