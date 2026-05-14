from itsdangerous import URLSafeTimedSerializer, BadSignature
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from typing import Optional
from datetime import datetime

from backend.config.settings import settings
from backend.models.sms import CardKey, get_session, engine

SESSION_COOKIE_NAME = "card_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # Cookie 最长保留7天


def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key)


def create_session_token(card_code: str) -> str:
    """生成签名 Token（内含卡密 code）"""
    serializer = get_serializer()
    return serializer.dumps(card_code, salt="card-session")


def verify_session_token(token: str) -> Optional[str]:
    """验证 Token，返回 card_code 或 None"""
    try:
        serializer = get_serializer()
        return serializer.loads(token, salt="card-session", max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    except Exception:
        return None


def get_card_from_request(request: Request) -> Optional[CardKey]:
    """从请求 Cookie 中提取并验证卡密，返回有效的 CardKey 或 None"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    card_code = verify_session_token(token)
    if not card_code:
        return None

    with Session(engine) as session:
        card = session.exec(select(CardKey).where(CardKey.code == card_code)).first()
        if not card or not card.is_active:
            return None

        # 懒删除：检查是否过期
        if card.expires_at and datetime.utcnow() > card.expires_at:
            session.delete(card)
            session.commit()
            return None

        # 返回一个脱离 session 的副本
        session.expunge(card)
        return card


async def require_valid_card(request: Request) -> CardKey:
    """
    依赖注入：从 Cookie 验证卡密有效性
    失败则重定向到 /login
    """
    card = get_card_from_request(request)
    if card is None:
        raise HTTPException(
            status_code=302,
            headers={"Location": "/login"},
            detail="请先输入卡密"
        )
    return card
