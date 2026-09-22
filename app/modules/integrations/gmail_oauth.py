"""Google OAuth 2.0 (Authorization Code flow) for the Gmail read-only scope.

Deliberately minimal: this app never needs anything beyond exchanging a
`code` for a refresh token once, and refreshing an access token thereafter.
No Google client SDK — plain httpx against Google's documented REST
endpoints, mirroring the pattern career-ops' own gmail plugins already use.
"""

from urllib.parse import urlencode

import httpx

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

# Read-only Gmail access is all LinkedIn alert ingestion needs — no send,
# modify, contacts, calendar, or Drive scope (Phase 5 Checkpoint C §3).
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class OAuthError(RuntimeError):
    pass


def build_authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        # Force a refresh_token even if the candidate previously granted
        # consent (Google otherwise omits it on a repeat grant).
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "false",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code_for_tokens(*, client_id: str, client_secret: str, redirect_uri: str, code: str, http_client: httpx.AsyncClient) -> dict:
    response = await http_client.post(TOKEN_ENDPOINT, data={"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri, "code": code, "grant_type": "authorization_code"})
    if response.status_code != 200:
        raise OAuthError(f"token exchange failed ({response.status_code})")
    data = response.json()
    if "refresh_token" not in data or "access_token" not in data:
        raise OAuthError("Google did not return a refresh_token — retry the connection (consent may need to be re-granted)")
    return data


async def refresh_access_token(*, client_id: str, client_secret: str, refresh_token: str, http_client: httpx.AsyncClient) -> str:
    response = await http_client.post(TOKEN_ENDPOINT, data={"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"})
    if response.status_code != 200:
        # Google answers invalid_grant for a revoked/expired refresh token —
        # this is the "visible disconnected/error state" the checkpoint asks for.
        raise OAuthError(f"token refresh failed ({response.status_code})")
    data = response.json()
    if "access_token" not in data:
        raise OAuthError("token refresh returned no access_token")
    return data["access_token"]


async def fetch_account_email(*, access_token: str, http_client: httpx.AsyncClient) -> str | None:
    response = await http_client.get(PROFILE_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        return None
    return response.json().get("emailAddress")
