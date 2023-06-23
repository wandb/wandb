import dataclasses
from typing import Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"


@dataclasses.dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: str = FIXTURE_SERVICE_PORT
    method: Literal["post"] = "post"


@dataclasses.dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: str = SERVICES_API_PORT
    method: Literal["put"] = "put"


@dataclasses.dataclass
class WandbServerSettings:
    name: str
    volume: str
    local_base_port: str
    services_api_port: str
    fixture_service_port: str
    wandb_server_pull: str
    wandb_server_tag: str
    internal_local_base_port: str = "8080"
    internal_local_services_api_port: str = "8083"
    internal_fixture_service_port: str = "9015"
