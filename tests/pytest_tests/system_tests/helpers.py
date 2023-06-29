from dataclasses import dataclass
from typing import Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"


def get_free_port():
    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    return str(sock.getsockname()[1])


@dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: str = FIXTURE_SERVICE_PORT
    method: Literal["post"] = "post"


@dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: str = SERVICES_API_PORT
    method: Literal["put"] = "put"


@dataclass
class WandbServerSettings:
    name: str
    volume: str
    local_base_port: str
    services_api_port: str
    fixture_service_port: str
    db_port: str
    wandb_server_pull: str
    wandb_server_tag: str
    internal_local_base_port: str = "8080"
    internal_local_services_api_port: str = "8083"
    internal_fixture_service_port: str = "9015"
    internal_db_port: str = "3306"
    url: str = "http://localhost"

    base_url: Optional[str] = None

    def __post_init__(self):
        self.base_url = f"{self.url}:{self.local_base_port}"


@dataclass
class WandbLoggingConfig:
    n_steps: int
    n_metrics: int
    n_experiments: int
    n_reports: int

    project_name: str = "test"


@dataclass
class WandbServerUser:
    server: WandbServerSettings
    user: str


@dataclass
class MlflowServerSettings:
    metrics_backend: Literal[
        "mssql_backend",
        "mysql_backend",
        "postgres_backend",
        "file_backend",
        "sqlite_backend",
    ]
    artifacts_backend: Literal["file_artifacts", "s3_artifacts"]

    base_url: str = "http://localhost:4040"
    health_endpoint: str = "health"

    # helper if port is blocked
    new_port: Optional[str] = None

    def __post_init__(self):
        self.new_port = get_free_port()
        self.base_url = self.base_url.replace("4040", self.new_port)


@dataclass
class MlflowLoggingConfig:
    # experiments and metrics
    n_experiments: int
    n_runs_per_experiment: int
    n_steps_per_run: int

    # artifacts
    n_root_files: int
    n_subdirs: int
    n_subdir_files: int

    # batching
    logging_batch_size: int = 50

    @property
    def total_runs(self):
        return self.n_experiments * self.n_runs_per_experiment

    @property
    def total_files(self):
        return self.n_root_files + self.n_subdirs * self.n_subdir_files
