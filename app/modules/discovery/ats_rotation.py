"""Persistent, deterministic reverse-ATS rotation (Phase 5 follow-up §C).

Replaces --shuffle (random, no coverage guarantee, no persistent state) for
AUTOMATED morning discovery with a per-provider cursor: each run scans the
next `batch_size` companies starting at `next_offset`, and the cursor only
advances on a SUCCESSFUL scan — a failed/partial run leaves next_offset
untouched so no company slice is silently skipped. Manual Explore Scan is
completely unaffected: it still calls scan-ats-full.mjs with --shuffle/no
--offset, a code path this module never touches.

DiscoveryRun already records automation history; this is intentionally just
a five-row cursor table (one per ATS source), not a second history system.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.discovery.models import AtsScanCursor
from app.modules.discovery.sources import REVERSE_SCAN_SOURCES

# Proposed daily batch sizes (Phase 5 follow-up report) — Greenhouse/Lever
# start large since their datasets are the best-measured and cheapest per
# company; iCIMS/Ashby smaller given their larger/less-measured runtimes;
# Workday deliberately conservative until a real production/staging runtime
# is measured (scan-ats-full.mjs timed out on Workday in this sandbox during
# Checkpoint D — unrelated to this change, but means its batch size here is
# a starting guess, not a measurement).
DEFAULT_BATCH_SIZES: dict[str, int] = {"greenhouse": 1500, "lever": 1500, "ashby": 500, "workday": 100, "icims": 700}


async def get_or_create_cursor(db: AsyncSession, source: str) -> AtsScanCursor:
    cursor = await db.scalar(select(AtsScanCursor).where(AtsScanCursor.source == source))
    if cursor is None:
        cursor = AtsScanCursor(id=uuid.uuid4(), source=source, next_offset=0)
        db.add(cursor)
        await db.flush()
    return cursor


def next_batch(cursor: AtsScanCursor, batch_size: int) -> tuple[int, int]:
    """(offset, limit) for the next scan — pure, so the rotation math is
    testable without a DB. Does not mutate `cursor` or advance anything;
    see advance_cursor, called only after a scan actually SUCCEEDS."""
    return cursor.next_offset, batch_size


async def advance_cursor(db: AsyncSession, cursor: AtsScanCursor, *, scanned_offset: int, batch_size: int, dataset_size: int, status: str, error: str | None = None) -> None:
    """Only call this after a scan attempt completes. On success, advances
    to `(scanned_offset + batch_size) % dataset_size` — wrapping cleanly
    when the slice reached (or crossed) the end of the dataset, and doing
    nothing destructive if the dataset shrank (the modulo just re-normalizes
    on the NEXT call, same as scan-ats-full.mjs's own sampleCompanies).
    On failure, next_offset is left untouched: a failed/partial slice must
    be retried tomorrow, not skipped."""
    cursor.dataset_size = dataset_size
    cursor.last_status = status
    cursor.last_error = error
    cursor.last_scanned_at = datetime.now(timezone.utc)
    if status == "ok" and dataset_size > 0:
        cursor.next_offset = (scanned_offset + batch_size) % dataset_size
    await db.flush()


async def ensure_all_cursors(db: AsyncSession) -> dict[str, AtsScanCursor]:
    return {source: await get_or_create_cursor(db, source) for source in sorted(REVERSE_SCAN_SOURCES)}
