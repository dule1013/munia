import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.automation.scheduler import morning_sweep_loop
from app.modules.discovery.service import fail_orphaned_runs
from app.modules.ai_config.routes import router as ai_config_router
from app.modules.artifacts.routes import router as artifacts_router
from app.modules.automation.routes import router as automation_router
from app.modules.auth.routes import router as auth_router
from app.modules.candidates.routes import router as candidates_router
from app.modules.discovery.routes import router as discovery_router
from app.modules.integrations.routes import router as integrations_router
from app.modules.jobs.routes import router as jobs_router
from app.modules.pipeline.routes import router as pipeline_router

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        orphaned = await fail_orphaned_runs()
        if orphaned:
            logger.warning("marked %d orphaned discovery runs as failed", orphaned)
    except Exception:
        logger.exception("could not reap orphaned discovery runs")
    sweep_task = None
    if get_settings().morning_sweep_schedule_utc:
        sweep_task = asyncio.create_task(morning_sweep_loop(settings))
        logger.info("morning sweep scheduled at %s UTC (ai=%s)", settings.morning_sweep_schedule_utc, settings.morning_sweep_ai)
    else:
        logger.info("morning sweep scheduler disabled (MORNING_SWEEP_SCHEDULE_UTC not set)")
    yield
    if sweep_task is not None:
        sweep_task.cancel()
        with suppress(asyncio.CancelledError):
            await sweep_task


app = FastAPI(title="Career Ops Portal API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Test-Clerk-User-Id"])
app.include_router(auth_router, prefix="/api/v1")
app.include_router(ai_config_router, prefix="/api/v1")
app.include_router(candidates_router, prefix="/api/v1")
app.include_router(discovery_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(pipeline_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
