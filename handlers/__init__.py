from aiogram import Router

from .channel import router as channel_router
from .commands import router as commands_router
from .admin import router as admin_router
from .relay import router as relay_router


def setup_routers() -> Router:
    router = Router()
    router.include_router(channel_router)
    router.include_router(commands_router)
    router.include_router(admin_router)
    # Relay is a private-chat catch-all and MUST stay last.
    router.include_router(relay_router)
    return router
