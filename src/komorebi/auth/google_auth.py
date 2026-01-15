"""Google OAuth authentication for Calendar API.

Handles OAuth 2.0 flow for Google Calendar access.
Token is cached locally for subsequent uses.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Read-only calendar access is sufficient for listing events
# Full access needed for creating events
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_credentials(
    credentials_path: Path,
    token_path: Path,
) -> Credentials:
    """Get or refresh Google Calendar credentials.

    On first run, opens browser for OAuth authorization.
    Subsequent runs use cached token.

    Args:
        credentials_path: Path to credentials.json (OAuth client secrets).
        token_path: Path to token.json (cached credentials).

    Returns:
        Valid Credentials object for Calendar API.

    Raises:
        FileNotFoundError: If credentials.json doesn't exist.
    """
    creds: Credentials | None = None

    # Try to load existing token
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # If no valid credentials, need to authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google Calendar credentials not found: {credentials_path}\n"
                    "Please download credentials.json from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for next run
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return creds
