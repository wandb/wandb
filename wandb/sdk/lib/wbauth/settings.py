"""Logic for setting auth-related parts of wandb.Settings."""

from wandb.sdk.wandb_settings import Settings

from .auth import Auth, AuthApiKey, AuthIdentityTokenFile


def set_auth_settings(settings: Settings, auth: Auth | None) -> None:
    """Set auth-related settings based on the given credentials.

    Auth settings fall into two categories:
    - Mutually exclusive settings used to determine the auth method to use,
      like api_key and identity_token file.
    - Additional data needed for the chosen auth method,
      like base_url and credentials_file.

    This function always updates the first kind, but only updates relevant
    settings of the second kind: in particular, auth=None does not clear
    base_url, and using an API key auth does not clear the credentials_file used
    for JWT auth. This may be important in legacy code that expects to store
    this information in settings even when logged out.

    Args:
        settings: The settings to update.
        auth: The credentials, or possibly None to clear auth-related settings.
    """
    if auth is None:
        settings.api_key = None
        settings.identity_token_file = None

    elif isinstance(auth, AuthApiKey):
        settings.api_key = auth.api_key
        settings.identity_token_file = None
        settings.base_url = auth.host.url

    elif isinstance(auth, AuthIdentityTokenFile):
        settings.api_key = None
        settings.identity_token_file = str(auth.path)
        settings.credentials_file = str(auth.credentials_path)
        settings.base_url = auth.host.url

    else:
        raise NotImplementedError(str(auth))
