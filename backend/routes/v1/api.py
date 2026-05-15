import asyncio
import hashlib
from fastapi import APIRouter, HTTPException, Header, Query, Depends, Request
from sqlmodel import Session, select
from typing import Optional, List
from datetime import datetime, timedelta

from backend.models.sms import SMSRecord, AdminPassword, get_session
from backend.models.schema import SMSRecordCreate, ResponseWrapper, SetPasswordRequest, VerifyPasswordRequest
from backend.services.sms_service import (
    extract_code_with_context,
    extract_phone_from_sim_slot,
    query_latest_code
)
from backend.config.settings import settings
from backend.services.auth_service import require_valid_card


def hash_password(password: str) -> str:
    """对密码进行SHA256哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return hash_password(plain_password) == hashed_password

# 创建API路由器
router = APIRouter(prefix="/v1/sms", tags=["sms"])

# API KEY 校验
def check_api_key(x_api_key: Optional[str] = Header(None)):
    # 如果设置了API_KEY，则进行验证
    if settings.requires_api_key:
        if (x_api_key != settings.api_key):
            raise HTTPException(status_code=403, detail="Unauthorized")
    # 如果没有设置API_KEY，则跳过验证
    return True

# 接收短信接口
@router.post("/receive")
async def receive_sms(
    payload: SMSRecordCreate, 
    session: Session = Depends(get_session),
    x_api_key: Optional[str] = Header(None)
):
    check_api_key(x_api_key)
    
    code = extract_code_with_context(payload.sms)
    extracted_phone = extract_phone_from_sim_slot(payload.sim_slot)
    
    record_data = payload.dict()
    record = SMSRecord(**record_data, extracted_code=code, phone_number=extracted_phone)
    
    session.add(record)
    session.commit()
    
    print(f"[RECEIVED] From: {payload.from_}, Code: {code}, Time: {payload.receive_time.isoformat()}")
    return ResponseWrapper(result="ok", code="SUCCESS", message="短信接收成功").dict()

# 获取验证码接口
@router.get("/code")
async def get_sms_code(
    phone_number: str = Query(...),
    platform_keyword: Optional[str] = Query(None),
    wait_timeout: int = Query(5)
):
    end_time = datetime.utcnow() + timedelta(seconds=wait_timeout)
    while datetime.utcnow() < end_time:
        code, record = query_latest_code(phone_number, platform_keyword)
        if code:
            return ResponseWrapper(
                result="ok",
                code="SUCCESS",
                message="验证码获取成功",
                data={
                    "code": code,
                    "matched_by": "keyword" if platform_keyword else "fallback",
                    "sms_excerpt": record.sms[:50],
                    "received_time": record.receive_time.isoformat()
                }
            ).dict()
        await asyncio.sleep(1)
    return ResponseWrapper(result="not_found", code="TIMEOUT", message="验证码超时未找到").dict()

# 历史记录接口
@router.get("/history", response_model=List[SMSRecord])
async def list_sms(
    request: Request,
    limit: int = Query(20),
    offset: int = Query(0),
    admin_password: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    # 管理员密码鉴权 或 Cookie 鉴权，二选一
    if admin_password:
        admin = session.exec(select(AdminPassword)).first()
        if not admin or not verify_password(admin_password, admin.password):
            raise HTTPException(status_code=403, detail="管理员密码错误")
    else:
        from backend.services.auth_service import get_card_from_request
        if get_card_from_request(request) is None:
            raise HTTPException(status_code=302, headers={"Location": "/login"}, detail="请先登录")
    records = session.exec(
        select(SMSRecord).order_by(SMSRecord.receive_time.desc()).offset(offset).limit(limit)
    ).all()
    return records

# 获取单条短信详情
@router.get("/{sms_id}", response_model=SMSRecord)
async def get_sms_detail(
    request: Request,
    sms_id: int,
    admin_password: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    # 管理员密码鉴权 或 Cookie 鉴权，二选一
    if admin_password:
        admin = session.exec(select(AdminPassword)).first()
        if not admin or not verify_password(admin_password, admin.password):
            raise HTTPException(status_code=403, detail="管理员密码错误")
    else:
        from backend.services.auth_service import get_card_from_request
        if get_card_from_request(request) is None:
            raise HTTPException(status_code=302, headers={"Location": "/login"}, detail="请先登录")
    record = session.get(SMSRecord, sms_id)
    if not record:
        raise HTTPException(status_code=404, detail="短信记录不存在")
    return record

# 删除所有短信记录（必须在 /{sms_id} 之前定义，否则 /history 会被 {sms_id} 捕获）
@router.delete("/history")
async def delete_all_sms(
    session: Session = Depends(get_session),
    x_api_key: Optional[str] = Header(None)
):
    # 验证数据库中的管理员密码（通过哈希验证）
    admin = session.exec(select(AdminPassword)).first()
    if not admin or not verify_password(x_api_key or "", admin.password):
        raise HTTPException(status_code=403, detail="您没有权限，无法执行删除操作")
    records = session.exec(select(SMSRecord)).all()
    count = 0
    for record in records:
        session.delete(record)
        count += 1
    session.commit()
    return ResponseWrapper(result="ok", code="SUCCESS", message=f"已删除 {count} 条短信记录").dict()

# # 设置管理员密码
# @router.post("/admin/password")
# async def set_admin_password(
#     request: SetPasswordRequest,
#     session: Session = Depends(get_session)
# ):
#     admin = session.exec(select(AdminPassword)).first()
#     hashed = hash_password(request.password)
#     if admin:
#         admin.password = hashed
#     else:
#         admin = AdminPassword(password=hashed)
#         session.add(admin)
#     session.commit()
#     return ResponseWrapper(result="ok", code="SUCCESS", message="管理员密码已设置").dict()

# 验证管理员密码
@router.post("/admin/verify")
async def verify_admin_password(
    request: VerifyPasswordRequest,
    session: Session = Depends(get_session)
):
    admin = session.exec(select(AdminPassword)).first()
    if not admin or not verify_password(request.password, admin.password):
        raise HTTPException(status_code=403, detail="密码错误")
    return ResponseWrapper(result="ok", code="SUCCESS", message="验证通过").dict()

# 删除短信记录
@router.delete("/{sms_id}")
async def delete_sms(
    sms_id: int,
    session: Session = Depends(get_session),
    x_api_key: Optional[str] = Header(None)
):
    # 验证管理员密码
    admin = session.exec(select(AdminPassword)).first()
    if not admin or not verify_password(x_api_key or "", admin.password):
        raise HTTPException(status_code=403, detail="您没有权限，无法执行删除操作")
    record = session.get(SMSRecord, sms_id)
    if not record:
        raise HTTPException(status_code=404, detail="短信记录不存在")
    session.delete(record)
    session.commit()
    return ResponseWrapper(result="ok", code="SUCCESS", message="短信记录已删除").dict()
