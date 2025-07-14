from typing import List, Optional
from google.auth import default, credentials
from google.oauth2 import service_account


def get_credentials(
    scopes: List[str], key_file_path: Optional[str] = None
) -> credentials.Credentials:
    """
    Get Google API credentials for the given scopes.

    Args:
        scopes: List of OAuth2 scopes to request.
        key_file_path: Optional path to a service account key file.

    Returns:
        A Google credentials object.
    """
    if key_file_path:
        return service_account.Credentials.from_service_account_file(
            key_file_path, scopes=scopes
        )
    else:
        creds, _ = default(scopes=scopes)
        return creds
