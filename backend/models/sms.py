from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional
from datetime import datetime
import os
from backend.config.settings import settings

VALID_DURATIONS = {1, 3, 7}

# 确保数据目录存在
def ensure_data_directory():
    # 从数据库URL中提取文件路径
    if settings.database_url.startswith('sqlite:///'):
        db_path = settings.database_url.replace('sqlite:///', '')
        # 获取目录路径
        dir_path = os.path.dirname(db_path)
        # 如果目录不为空且不存在，则创建目录
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"已创建数据目录: {dir_path}")

# 确保数据目录存在
ensure_data_directory()

# 数据库引擎
engine = create_engine(settings.database_url, echo=False, connect_args=settings.db_connect_args)

# 数据模型
class SMSRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_: str = Field(..., alias='from')
    contact_name: Optional[str]
    phone_area: Optional[str]
    sms: str
    sim_slot: Optional[str]
    sim_sub_id: Optional[str]
    device_name: Optional[str]
    receive_time: datetime
    extracted_code: Optional[str] = None
    phone_number: Optional[str] = None  # 从 sim_slot 中提取的手机号

# 管理员密码表
class AdminPassword(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    password: str = Field(...)  # 管理员密码

# 卡密表
class CardKey(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(..., unique=True, index=True, max_length=8)  # 明文卡密
    duration_days: int = Field(...)                                     # 1 / 3 / 7
    created_at: datetime = Field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = Field(default=None)            # 首次使用时间
    expires_at: Optional[datetime] = Field(default=None)              # 到期时间
    is_active: bool = Field(default=False)

# 创建表结构
def create_db_and_tables():
    # 确保数据目录存在
    ensure_data_directory()
    SQLModel.metadata.create_all(engine)

# 创建会话工厂
def get_session():
    with Session(engine) as session:
        yield session
