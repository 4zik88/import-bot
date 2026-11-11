from aiogram import Router

from bot.handlers import common, import_cmd, products, schedule, setup, templates


def get_root_router() -> Router:
    router = Router()
    router.include_router(common.router)
    router.include_router(setup.router)
    router.include_router(products.router)
    router.include_router(import_cmd.router)
    router.include_router(schedule.router)
    router.include_router(templates.router)
    return router
