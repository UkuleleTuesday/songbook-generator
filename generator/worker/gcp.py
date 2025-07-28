from typing import List, Optional
from google.auth import default, credentials, impersonated_credentials


def get_credentials(
    scopes: List[str], target_principal: Optional[str] = None
) -> credentials.Credentials:
    """
    Get Google API credentials for given scopes, with optional impersonation.

    Args:
        scopes: List of OAuth2 scopes to request.
        target_principal: The service account to impersonate.

    Returns:
        A Google credentials object.
    """
    creds, _ = default(scopes=scopes)

    if target_principal:
        creds = impersonated_credentials.Credentials(
            source_credentials=creds,
            target_principal=target_principal,
            target_scopes=scopes,
        )

    return creds
