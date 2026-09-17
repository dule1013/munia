import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.migration.service import migrate_legacy_candidate


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--clerk-user-id", required=True)
    args = parser.parse_args()
    async with SessionLocal() as db:
        user, backup = await migrate_legacy_candidate(db, args.source, get_settings(), args.clerk_user_id)
        print(f"Migrated candidate {user.id}; backup: {backup}")


if __name__ == "__main__":
    asyncio.run(main())
