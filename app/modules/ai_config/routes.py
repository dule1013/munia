from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.modules.ai_config import service
from app.modules.ai_config.schemas import AIConfigSet, AIConfigStatus, AIModelOption
from app.modules.auth.dependencies import get_current_user
from app.modules.candidates.models import User

router = APIRouter(prefix="/ai-config", tags=["ai-config"])


def _model_options() -> list[AIModelOption]:
    return [AIModelOption(id=model_id, **meta) for model_id, meta in service.ANTHROPIC_MODELS.items()]


@router.get("/status", response_model=AIConfigStatus)
async def ai_config_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AIConfigStatus:
    config = await service.get_ai_config(db, user.id)
    if config is None:
        return AIConfigStatus(configured=False, available_models=_model_options())
    return AIConfigStatus(configured=True, provider=config.provider, model=config.model, updated_at=config.updated_at, available_models=_model_options())


@router.put("", response_model=AIConfigStatus)
async def set_ai_config(payload: AIConfigSet, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> AIConfigStatus:
    if not settings.integration_encryption_key:
        raise HTTPException(status_code=503, detail="AI configuration storage is not available on this deployment")
    try:
        config = await service.set_api_key(db, settings, user_id=user.id, provider=payload.provider, model=payload.model, api_key=payload.api_key)
    except (service.UnsupportedModel, service.UnsupportedProvider, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await db.commit()
    return AIConfigStatus(configured=True, provider=config.provider, model=config.model, updated_at=config.updated_at, available_models=_model_options())


@router.delete("", status_code=204)
async def delete_ai_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await service.remove_ai_config(db, user.id)
    await db.commit()
