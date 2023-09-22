import json
import os

from wandb_gql import Client

from wandb import env
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib.gql_request import GraphQLSession


def build_gql_client(user_agent, api_key, settings, environ=os.environ, timeout=None):
    extra_http_headers = settings("_extra_http_headers") or json.loads(
        environ.get("WANDB__EXTRA_HTTP_HEADERS", "{}")
    )
    proxies = settings("_proxies") or json.loads(environ.get("WANDB__PROXIES", "{}"))
    auth = None
    if _thread_local_api_settings.cookies is None:
        auth = ("api", api_key or "")
    extra_http_headers.update(_thread_local_api_settings.headers or {})

    transport = GraphQLSession(
        headers={
            "User-Agent": user_agent,
            "Use-Admin-Privileges": "true",
            "X-WANDB-USERNAME": env.get_username(env=environ),
            "X-WANDB-USER-EMAIL": env.get_user_email(env=environ),
            **extra_http_headers,
        },
        use_json=True,
        # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
        # https://bugs.python.org/issue22889
        timeout=timeout or env.get_http_timeout(20),
        auth=auth,
        url=f"{settings('base_url')}/graphql",
        cookies=_thread_local_api_settings.cookies,
        proxies=proxies,
    )
    return Client(transport)
