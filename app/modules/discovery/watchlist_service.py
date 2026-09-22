import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.discovery.models import WatchedCompany
from app.modules.discovery.sources import detect_provider
from app.modules.discovery.watchlist_schemas import WatchedCompanyCreate, WatchedCompanyUpdate

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_company_key(company_name: str) -> str:
    return _WHITESPACE_RE.sub(" ", company_name.strip().casefold())


async def list_watched_companies(db: AsyncSession, user_id: uuid.UUID) -> list[WatchedCompany]:
    rows = await db.scalars(select(WatchedCompany).where(WatchedCompany.user_id == user_id).order_by(WatchedCompany.priority.desc(), WatchedCompany.company_name))
    return list(rows)


async def get_watched_company(db: AsyncSession, user_id: uuid.UUID, company_id: uuid.UUID) -> WatchedCompany | None:
    return await db.scalar(select(WatchedCompany).where(WatchedCompany.id == company_id, WatchedCompany.user_id == user_id))


async def create_watched_company(db: AsyncSession, user_id: uuid.UUID, payload: WatchedCompanyCreate) -> WatchedCompany:
    key = normalize_company_key(payload.company_name)
    existing = await db.scalar(select(WatchedCompany).where(WatchedCompany.user_id == user_id, WatchedCompany.company_key == key))
    if existing is not None:
        raise ValueError("company already on watchlist")
    provider, tenant = detect_provider(payload.careers_url or "")
    company = WatchedCompany(
        user_id=user_id,
        company_name=payload.company_name.strip(),
        company_key=key,
        careers_url=payload.careers_url,
        provider=provider,
        provider_tenant_id=tenant,
        priority=payload.priority,
        enabled=payload.enabled,
        scan_status="never_scanned",
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


async def update_watched_company(db: AsyncSession, company: WatchedCompany, payload: WatchedCompanyUpdate) -> WatchedCompany:
    changes = payload.model_dump(exclude_unset=True)
    if "company_name" in changes:
        company.company_name = changes["company_name"].strip()
        company.company_key = normalize_company_key(changes["company_name"])
    if "careers_url" in changes:
        company.careers_url = changes["careers_url"]
        company.provider, company.provider_tenant_id = detect_provider(changes["careers_url"] or "")
    if "priority" in changes:
        company.priority = changes["priority"]
    if "enabled" in changes:
        company.enabled = changes["enabled"]
    await db.commit()
    await db.refresh(company)
    return company


async def delete_watched_company(db: AsyncSession, company: WatchedCompany) -> None:
    await db.delete(company)
    await db.commit()


async def mark_scan_status(db: AsyncSession, watchlist_entry_ids: tuple[uuid.UUID, ...], *, status: str, error: str | None) -> None:
    """Persist a scan outcome onto every WatchedCompany row sharing a scan
    target (Checkpoint D §4) — deliberately small: detected provider/tenant
    were already set at create/update time, so a scan only ever updates
    last_scanned_at/scan_status/last_scan_error, never the full response."""
    if not watchlist_entry_ids:
        return
    rows = list(await db.scalars(select(WatchedCompany).where(WatchedCompany.id.in_(watchlist_entry_ids))))
    now = utcnow()
    for row in rows:
        row.scan_status = status
        row.last_scan_error = error
        row.last_scanned_at = now
    await db.commit()


@dataclass(frozen=True)
class ScanTarget:
    """One distinct company to scan, shared across every candidate watching
    it. Canonical Jobs are global, so scanning the same company once on
    behalf of every watcher (rather than once per candidate) avoids the
    duplicate-network-work Phase 5 §6/§11 calls out. Scanning execution
    itself is a Checkpoint C/D concern — this only groups the targets."""

    company_key: str
    company_name: str
    careers_url: str | None
    provider: str | None
    provider_tenant_id: str | None
    watcher_user_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    watchlist_entry_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


async def distinct_scan_targets(db: AsyncSession, *, enabled_only: bool = True) -> list[ScanTarget]:
    """Group every candidate's watchlist entries by normalized target
    (careers_url when known, else company_key) so a shared company is
    identified once regardless of how many candidates watch it.

    Watchlist preferences (priority, enabled, per-candidate notes) stay
    private; only the resulting scan target — the thing that would actually
    be scanned — is deduplicated here.
    """
    query = select(WatchedCompany)
    if enabled_only:
        query = query.where(WatchedCompany.enabled.is_(True))
    rows = list(await db.scalars(query))

    grouped: dict[str, list[WatchedCompany]] = {}
    for row in rows:
        target_key = (row.careers_url or "").strip().casefold() or f"name:{row.company_key}"
        grouped.setdefault(target_key, []).append(row)

    targets: list[ScanTarget] = []
    for entries in grouped.values():
        representative = min(entries, key=lambda e: e.created_at)
        targets.append(
            ScanTarget(
                company_key=representative.company_key,
                company_name=representative.company_name,
                careers_url=representative.careers_url,
                provider=representative.provider,
                provider_tenant_id=representative.provider_tenant_id,
                watcher_user_ids=tuple(dict.fromkeys(e.user_id for e in entries)),
                watchlist_entry_ids=tuple(e.id for e in entries),
            )
        )
    return targets
