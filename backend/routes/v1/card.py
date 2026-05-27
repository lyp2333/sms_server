import re
import secrets
import hashlib
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel

from backend.models.sms import CardKey, AdminPassword, get_session
from backend.services.auth_service import (
    create_session_token,
    verify_session_token,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
)
from backend.middlewares.rate_limit import check_rate_limit, record_failed_attempt, clear_failed_attempts, get_client_ip
from backend.config.settings import settings


card_router = APIRouter(prefix="/v1/card", tags=["card"])


# ── 请求/响应 Schema ──────────────────────────────────────────────────────────

class VerifyCardRequest(BaseModel):
    code: str

class CreateCardRequest(BaseModel):
    admin_password: str
    duration_days: int          # 1 / 3 / 7
    count: int = 1              # 批量生成数量

class AdminPasswordRequest(BaseModel):
    admin_password: str


class ExtendDaysRequest(BaseModel):
    admin_password: str
    days: int


class CardResponse(BaseModel):
    code: str
    duration_days: int
    created_at: datetime
    activated_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_active: bool
    status: str                 # "unused" / "active" / "expired"


# ── 内部工具函数 ──────────────────────────────────────────────────────────────

VALID_DURATION_DAYS = {1, 3, 7, 15, 30}
CARD_RE = re.compile(r'^[A-Z0-9]{8}$')


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_admin(plain_password: str, session: Session) -> bool:
    admin = session.exec(select(AdminPassword)).first()
    if not admin:
        return False
    return hash_password(plain_password) == admin.password


def generate_card_code(session: Session) -> str:
    """生成唯一卡密，最多重试 20 次"""
    charset = settings.card_key_charset
    length = settings.card_key_length
    for _ in range(20):
        code = ''.join(secrets.choice(charset) for _ in range(length))
        existing = session.exec(select(CardKey).where(CardKey.code == code)).first()
        if not existing:
            return code
    raise RuntimeError("无法生成唯一卡密，请稍后重试")


def card_status(card: CardKey) -> str:
    if not card.is_active:
        return "unused"
    if card.expires_at and datetime.utcnow() > card.expires_at:
        return "expired"
    return "active"


def card_to_response(card: CardKey) -> CardResponse:
    return CardResponse(
        code=card.code,
        duration_days=card.duration_days,
        created_at=card.created_at,
        activated_at=card.activated_at,
        expires_at=card.expires_at,
        is_active=card.is_active,
        status=card_status(card),
    )


def cleanup_expired(session: Session) -> int:
    """删除所有已过期卡密，返回删除数量"""
    now = datetime.utcnow()
    expired = session.exec(
        select(CardKey).where(
            CardKey.is_active == True,
            CardKey.expires_at < now,
        )
    ).all()
    count = len(expired)
    for card in expired:
        session.delete(card)
    if count:
        session.commit()
    return count


# ── 用户端接口 ────────────────────────────────────────────────────────────────

@card_router.post("/verify")
async def verify_card(
    request: Request,
    response: Response,
    body: VerifyCardRequest,
    session: Session = Depends(get_session),
):
    """验证卡密并写入 Session Cookie"""
    client_ip = get_client_ip(request)

    # 格式预校验（减少无效查库）
    code = body.code.strip().upper()
    if not CARD_RE.match(code):
        record_failed_attempt(client_ip)
        raise HTTPException(status_code=400, detail="卡密格式错误（需8位大写字母或数字）")

    # IP 限速检查
    allowed, wait_seconds = check_rate_limit(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"尝试次数过多，请等待 {wait_seconds} 秒后重试",
        )

    card = session.exec(select(CardKey).where(CardKey.code == code)).first()

    if not card:
        record_failed_attempt(client_ip)
        # 固定延迟，防止时序旁路
        await asyncio.sleep(1)
        raise HTTPException(status_code=400, detail="卡密无效")

    # 懒删除：已激活且已过期
    if card.is_active and card.expires_at and datetime.utcnow() > card.expires_at:
        session.delete(card)
        session.commit()
        record_failed_attempt(client_ip)
        raise HTTPException(status_code=400, detail="卡密已过期")

    # 首次激活
    if not card.is_active:
        card.is_active = True
        card.activated_at = datetime.utcnow()
        card.expires_at = card.activated_at + timedelta(days=card.duration_days)
        try:
            session.add(card)
            session.commit()
            session.refresh(card)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="激活失败，请重试")

    # 清除此 IP 的失败记录
    clear_failed_attempts(client_ip)

    # 颁发 Session Cookie
    token = create_session_token(card.code)
    remaining_seconds = int((card.expires_at - datetime.utcnow()).total_seconds())
    cookie_max_age = min(SESSION_MAX_AGE, remaining_seconds)

    resp_data = {
        "result": "ok",
        "message": "验证成功",
        "expires_at": card.expires_at.isoformat(),
        "remaining_hours": remaining_seconds // 3600,
    }

    from fastapi.responses import JSONResponse
    json_response = JSONResponse(content=resp_data)
    json_response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=cookie_max_age,
        httponly=True,
        samesite="strict",
        secure=False,   # 生产 HTTPS 时改 True
    )
    return json_response


@card_router.get("/status")
async def card_status_endpoint(
    request: Request,
    session: Session = Depends(get_session),
):
    """查询当前 Cookie 对应的卡密状态"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    card_code = verify_session_token(token)
    if not card_code:
        raise HTTPException(status_code=401, detail="Session 无效或已过期")

    card = session.exec(select(CardKey).where(CardKey.code == card_code)).first()
    if not card:
        raise HTTPException(status_code=401, detail="卡密不存在")

    if card.expires_at and datetime.utcnow() > card.expires_at:
        session.delete(card)
        session.commit()
        raise HTTPException(status_code=401, detail="卡密已过期")

    remaining = int((card.expires_at - datetime.utcnow()).total_seconds())
    return {
        "result": "ok",
        "code": card.code,
        "expires_at": card.expires_at.isoformat(),
        "remaining_hours": remaining // 3600,
        "remaining_seconds": remaining,
    }


@card_router.post("/logout")
async def logout(response: Response):
    """退出登录，清除 Cookie"""
    from fastapi.responses import JSONResponse
    json_response = JSONResponse(content={"result": "ok", "message": "已退出登录"})
    json_response.delete_cookie(SESSION_COOKIE_NAME)
    return json_response


# ── 管理员接口 ────────────────────────────────────────────────────────────────

@card_router.post("/admin/create")
async def create_cards(
    body: CreateCardRequest,
    session: Session = Depends(get_session),
):
    """批量创建卡密（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    if body.duration_days not in VALID_DURATION_DAYS:
        raise HTTPException(status_code=400, detail="有效期只能为 1、3、7 天")

    if body.count < 1 or body.count > 100:
        raise HTTPException(status_code=400, detail="单次生成数量限 1~100 个")

    created_codes: List[str] = []
    for _ in range(body.count):
        code = generate_card_code(session)
        card = CardKey(
            code=code,
            duration_days=body.duration_days,
            created_at=datetime.utcnow(),
        )
        session.add(card)
        created_codes.append(code)

    session.commit()
    return {
        "result": "ok",
        "message": f"成功创建 {len(created_codes)} 个卡密",
        "codes": created_codes,
        "duration_days": body.duration_days,
    }


@card_router.get("/admin/list")
async def list_cards(
    admin_password: str,
    session: Session = Depends(get_session),
):
    """查看所有卡密（管理员）"""
    if not verify_admin(admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    cards = session.exec(select(CardKey).order_by(CardKey.created_at.desc())).all()
    return {
        "result": "ok",
        "total": len(cards),
        "cards": [card_to_response(c).dict() for c in cards],
    }


@card_router.delete("/admin/{code}")
async def delete_card(
    code: str,
    body: AdminPasswordRequest,
    session: Session = Depends(get_session),
):
    """删除单个卡密（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    card = session.exec(select(CardKey).where(CardKey.code == code.upper())).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")

    session.delete(card)
    session.commit()
    return {"result": "ok", "message": f"卡密 {code.upper()} 已删除"}


@card_router.post("/admin/{code}/expire")
async def expire_card(
    code: str,
    body: AdminPasswordRequest,
    session: Session = Depends(get_session),
):
    """使卡密立即失效（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    card = session.exec(select(CardKey).where(CardKey.code == code.upper())).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")
    if not card.is_active:
        raise HTTPException(status_code=400, detail="卡密尚未激活，无需失效")

    card.expires_at = datetime.utcnow()
    session.add(card)
    session.commit()
    return {"result": "ok", "message": f"卡密 {code.upper()} 已设为失效"}


@card_router.post("/admin/{code}/extend")
async def extend_card_days(
    code: str,
    body: ExtendDaysRequest,
    session: Session = Depends(get_session),
):
    """延长卡密有效天数（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    card = session.exec(select(CardKey).where(CardKey.code == code.upper())).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")

    # 未激活的卡密不能增加天数
    if not card.is_active:
        raise HTTPException(status_code=400, detail="卡密尚未激活，无法增加天数")

    # 如果卡密已过期，删除旧记录重新创建激活流程
    if card.expires_at and datetime.utcnow() > card.expires_at:
        session.delete(card)
        session.commit()
        card = CardKey(
            code=code.upper(),
            duration_days=body.days,
            is_active=True,
            activated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=body.days),
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        return {"result": "ok", "message": f"卡密 {code.upper()} 已过期，原卡密已删除，新卡密已激活，有效期 {body.days} 天"}

    # 延长有效期
    card.expires_at = card.expires_at + timedelta(days=body.days)
    session.add(card)
    session.commit()
    return {"result": "ok", "message": f"已延长 {body.days} 天，新到期时间: {card.expires_at.strftime('%Y-%m-%d %H:%M:%S')}"}


@card_router.post("/admin/cleanup")
async def manual_cleanup(
    body: AdminPasswordRequest,
    session: Session = Depends(get_session),
):
    """手动清理过期卡密（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    count = cleanup_expired(session)
    return {"result": "ok", "message": f"已清理 {count} 个过期卡密"}


@card_router.post("/admin/cleanup-unused")
async def cleanup_unused(
    body: AdminPasswordRequest,
    session: Session = Depends(get_session),
):
    """删除所有未激活卡密（管理员）"""
    if not verify_admin(body.admin_password, session):
        raise HTTPException(status_code=403, detail="管理员密码错误")

    unused = session.exec(
        select(CardKey).where(CardKey.is_active == False)
    ).all()
    count = len(unused)
    for card in unused:
        session.delete(card)
    if count:
        session.commit()
    return {"result": "ok", "message": f"已删除 {count} 个未激活卡密"}
