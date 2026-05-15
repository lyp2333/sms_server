import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.config.settings import settings
from backend.middlewares.logging_middleware import logging_middleware
from backend.middlewares.rate_limit import rate_limit_middleware
from backend.models.sms import create_db_and_tables, ensure_data_directory, engine
from backend.routes.v1.api import router
from backend.routes.v1.card import card_router
from backend.services.auth_service import require_valid_card, SESSION_COOKIE_NAME
from backend.utils.logger import setup_logging
from sqlmodel import Session, select
from datetime import datetime

# 设置日志配置
logger = setup_logging()


async def periodic_cleanup():
    """每小时清理一次过期卡密"""
    from backend.models.sms import CardKey
    while True:
        await asyncio.sleep(3600)
        try:
            with Session(engine) as session:
                expired = session.exec(
                    select(CardKey).where(
                        CardKey.expires_at < datetime.utcnow(),
                        CardKey.is_active == True
                    )
                ).all()
                count = len(expired)
                for card in expired:
                    session.delete(card)
                session.commit()
                if count:
                    logger.info(f"定时清理：已删除 {count} 个过期卡密")
        except Exception as e:
            logger.error(f"定时清理异常: {e}")


def cleanup_expired_cards_once():
    """启动时清理过期卡密"""
    from backend.models.sms import CardKey
    try:
        with Session(engine) as session:
            expired = session.exec(
                select(CardKey).where(
                    CardKey.expires_at < datetime.utcnow(),
                    CardKey.is_active == True
                )
            ).all()
            count = len(expired)
            for card in expired:
                session.delete(card)
            session.commit()
            if count:
                logger.info(f"启动清理：已删除 {count} 个过期卡密")
    except Exception as e:
        logger.error(f"启动清理异常: {e}")


# 创建 lifespan 上下文管理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_directory()
    create_db_and_tables()
    logger.info("数据库表已初始化")
    cleanup_expired_cards_once()
    task = asyncio.create_task(periodic_cleanup())
    yield
    task.cancel()
    logger.info("应用已关闭")


# 创建应用
app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    debug=(settings.log_level == "debug"),
    lifespan=lifespan
)

# 注册路由和中间件
app.include_router(router)
app.include_router(card_router)
app.middleware("http")(logging_middleware)
app.middleware("http")(rate_limit_middleware)

# 配置静态文件和模板
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "templates")
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "static")

templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# 主页路由（需要卡密验证）
@app.get("/", tags=["UI"])
async def index(request: Request):
    logger.debug("访问主页路由")
    card = await require_valid_card(request)
    if isinstance(card, RedirectResponse):
        return card

    # 计算剩余时间
    remaining_hours = None
    card_expires_timestamp = None
    if card.expires_at:
        delta = card.expires_at - datetime.utcnow()
        remaining_hours = max(0, int(delta.total_seconds() / 3600))
        # expires_at 是 UTC naive datetime，用 calendar.timegm 避免本地时区偏差
        import calendar
        card_expires_timestamp = calendar.timegm(card.expires_at.timetuple())

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "card_expires_in_hours": remaining_hours,
            "card_expires_timestamp": card_expires_timestamp,
        },
    )


# 卡密登录页
@app.get("/login", tags=["UI"])
async def login_page(request: Request):
    # 如果已经有有效 Cookie，直接跳转主页
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        card = await require_valid_card(request)
        if not isinstance(card, RedirectResponse):
            return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request=request, name="card_login.html")


# 管理员卡密管理页
@app.get("/admin/cards", tags=["UI"])
async def admin_cards_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_cards.html")


# 使用该方法启动应用: uvicorn backend.main:app --host 0.0.0.0 --port 8322
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=False, log_level=settings.log_level)
