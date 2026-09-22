"""Thin Gmail REST client for LinkedIn alert ingestion. Read-only scope only
(gmail.readonly) — never sends, modifies, or deletes anything. Plain httpx,
no Google SDK, mirroring the pattern career-ops' own bundled/registered
gmail plugins use.
"""

from datetime import date, timedelta

import httpx

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailApiError(RuntimeError):
    pass


def _gmail_date(days_back: int) -> str:
    d = date.today() - timedelta(days=days_back)
    return f"{d.year}/{d.month:02d}/{d.day:02d}"


async def list_messages(*, access_token: str, http_client: httpx.AsyncClient, sender: str, days_back: int = 7, max_results: int = 50) -> list[dict]:
    query = f"from:{sender} after:{_gmail_date(days_back)}"
    response = await http_client.get(f"{GMAIL_BASE}/messages", params={"q": query, "maxResults": max_results}, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise GmailApiError(f"Gmail messages.list failed ({response.status_code})")
    return response.json().get("messages") or []


async def get_message(*, access_token: str, http_client: httpx.AsyncClient, message_id: str) -> dict:
    response = await http_client.get(f"{GMAIL_BASE}/messages/{message_id}", params={"format": "full"}, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise GmailApiError(f"Gmail messages.get failed ({response.status_code})")
    return response.json()
