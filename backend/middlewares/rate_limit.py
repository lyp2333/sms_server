"""
IP 滑动窗口限速中间件
60秒内最多5次失败尝试，锁定5分钟
"""
import time
from collections import defaultdict
from typing import Dict, List, Tuple

# 失败记录：{ip: [timestamp, ...]}
failed_attempts: Dict[str, List[float]] = defaultdict(list)
# 锁定记录：{ip: unlock_timestamp}
lockout_until: Dict[str, float] = {}

WINDOW = 60       # 滑动窗口（秒）
MAX_FAILS = 5     # 最大失败次数
LOCKOUT = 60      # 锁定时长（秒）


def is_ip_locked(ip: str) -> bool:
    """检查 IP 是否被锁定"""
    now = time.time()
    if ip in lockout_until:
        if now < lockout_until[ip]:
            return True
        else:
            del lockout_until[ip]
            failed_attempts.pop(ip, None)
    return False


def get_lockout_remaining(ip: str) -> int:
    """获取锁定剩余秒数"""
    now = time.time()
    if ip in lockout_until and now < lockout_until[ip]:
        return int(lockout_until[ip] - now)
    return 0


def check_rate_limit(ip: str) -> Tuple[bool, int]:
    """
    检查 IP 是否可继续请求
    返回 (是否允许, 锁定剩余秒数)
    """
    if is_ip_locked(ip):
        return False, get_lockout_remaining(ip)
    return True, 0


def record_failed_attempt(ip: str) -> int:
    """
    记录一次失败尝试
    返回当前窗口内的失败次数
    """
    now = time.time()
    failed_attempts[ip] = [t for t in failed_attempts[ip] if now - t < WINDOW]
    failed_attempts[ip].append(now)
    count = len(failed_attempts[ip])

    if count >= MAX_FAILS:
        lockout_until[ip] = now + LOCKOUT
        failed_attempts.pop(ip, None)

    return count


def clear_failed_attempts(ip: str):
    """验证成功后清除该 IP 的失败记录"""
    failed_attempts.pop(ip, None)
    lockout_until.pop(ip, None)


def get_client_ip(request) -> str:
    """从请求中提取客户端 IP（兼容反向代理）"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request, call_next):
    """
    全局 HTTP 中间件：对非 /v1/card/verify 路径不做限制，
    verify 路径的限速在路由层 card.py 中处理。
    这里仅负责捕获已知被锁定的 IP 快速拒绝。
    """
    # 仅对卡密验证接口启用
    if request.url.path not in ("/v1/card/verify",):
        return await call_next(request)

    ip = get_client_ip(request)
    allowed, wait_seconds = check_rate_limit(ip)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": f"尝试次数过多，请等待 {wait_seconds} 秒后重试"}
        )

    return await call_next(request)
