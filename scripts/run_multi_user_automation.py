import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.automation.batch import direct_discovery, level3_all, linkedin_alert_sync_all, morning_run, reverse_discovery, triage_all, watchlist_all


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["daily", "morning", "greenhouse", "lever", "ashby", "workday", "icims", "level3", "triage", "linkedin", "watchlist"])
    parser.add_argument("--no-ai", action="store_true", help="morning mode only: a controlled run with every AI-dependent step disabled (zero paid Anthropic calls) — see automation.batch.morning_run(disable_ai=...)")
    args = parser.parse_args()
    settings = get_settings()
    async with SessionLocal() as db:
        if args.mode == "morning":
            result = await morning_run(db, settings, disable_ai=args.no_ai)
        elif args.mode == "daily":
            result = await direct_discovery(db, settings)
        elif args.mode == "level3":
            result = await level3_all(db, settings)
        elif args.mode == "triage":
            result = await triage_all(db, settings)
        elif args.mode == "linkedin":
            result = await linkedin_alert_sync_all(db, settings)
        elif args.mode == "watchlist":
            result = await watchlist_all(db, settings)
        else:
            limits = {"greenhouse": 1500, "lever": 1500, "ashby": 300, "workday": 200, "icims": 300}
            result = await reverse_discovery(db, settings, args.mode, limits[args.mode])
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
