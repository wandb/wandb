from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class UserConfig:
    admin: bool = False
    enable_runs_v2: bool = False
