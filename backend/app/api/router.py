from fastapi import APIRouter

from app.api.routes import cyclic, game_config, game_context, gaf, health, obs, ocr, payline, roi, symbol

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(game_context.router)
api_router.include_router(game_config.router)
api_router.include_router(obs.router)
api_router.include_router(gaf.router)
api_router.include_router(roi.router)
api_router.include_router(ocr.router)
api_router.include_router(symbol.router)
api_router.include_router(payline.router)
api_router.include_router(cyclic.router)
