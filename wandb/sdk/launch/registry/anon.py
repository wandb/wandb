from typing import Tuple

from .abstract import AbstractRegistry


class AnonynmousRegistry(AbstractRegistry):
    def __init__(self, uri: str) -> None:
        """Initialize the registry."""
        self.uri = uri

    async def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry."""
        raise NotImplementedError("Anonymous registry does not require authentication")

    async def get_repo_uri(self) -> str:
        return self.uri

    async def check_image_exists(self, image_uri: str) -> bool:
        raise NotImplementedError(
            "Anonymous registry does not support checking image existence"
        )

    @classmethod
    def from_config(cls, config: dict) -> "AbstractRegistry":
        return cls(uri=config["uri"])
