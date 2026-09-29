from fastapi import APIRouter

from app.api.routes import game_config, game_context, health, obs, roi

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(game_context.router)
api_router.include_router(game_config.router)
api_router.include_router(obs.router)
api_router.include_router(roi.router)
