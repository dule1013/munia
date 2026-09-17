import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.automation.batch import direct_discovery, level3_all, reverse_discovery, triage_all


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["daily", "greenhouse", "lever", "ashby", "workday", "level3", "triage"])
    args = parser.parse_args()
    settings = get_settings()
    async with SessionLocal() as db:
        if args.mode == "daily":
            result = await direct_discovery(db, settings)
        elif args.mode == "level3":
            result = await level3_all(db, settings)
        elif args.mode == "triage":
            result = await triage_all(db, settings)
        else:
            limits = {"greenhouse": 1500, "lever": 1500, "ashby": 300, "workday": 200}
            result = await reverse_discovery(db, settings, args.mode, limits[args.mode])
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
