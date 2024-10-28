# originally: https://github.com/docker/docker-py/blob/master/docker/auth.py
import base64
import json
import logging
import os
import platform
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import dockerpycreds  # type: ignore

IS_WINDOWS_PLATFORM = platform.system() == "Windows"
DOCKER_CONFIG_FILENAME = os.path.join(".docker", "config.json")
LEGACY_DOCKER_CONFIG_FILENAME = ".dockercfg"
INDEX_NAME = "docker.io"
INDEX_URL = f"https://index.{INDEX_NAME}/v1/"
TOKEN_USERNAME = "<token>"

log = logging.getLogger(__name__)


class DockerError(Exception):
    """Base class from which all other exceptions inherit.

    If you want to catch all errors that the Docker SDK might raise,
    catch this base exception.
    """


class InvalidConfigFileError(DockerError):
    pass


class InvalidRepositoryError(DockerError):
    pass


def find_config_file(config_path: Optional[str] = None) -> Optional[str]:
    paths = list(
        filter(
            None,
            [
                config_path,  # 1
                config_path_from_environment(),  # 2
                os.path.join(home_dir(), DOCKER_CONFIG_FILENAME),  # 3
                os.path.join(home_dir(), LEGACY_DOCKER_CONFIG_FILENAME),  # 4
            ],
        )
    )

    log.debug(f"Trying paths: {repr(paths)}")

    for path in paths:
        if os.path.exists(path):
            log.debug(f"Found file at path: {path}")
            return path

    log.debug("No config file found")

    return None


def config_path_from_environment() -> Optional[str]:
    config_dir = os.environ.get("DOCKER_CONFIG")
    if not config_dir:
        return None
    return os.path.join(config_dir, os.path.basename(DOCKER_CONFIG_FILENAME))


def home_dir() -> str:
    """Get the user's home directory.

    Uses the same logic as the Docker Engine client - use %USERPROFILE% on Windows,
    $HOME/getuid on POSIX.
    """
    if IS_WINDOWS_PLATFORM:
        return os.environ.get("USERPROFILE", "")
    else:
        return os.path.expanduser("~")


def load_general_config(config_path: Optional[str] = None) -> Dict:
    config_file = find_config_file(config_path)

    if not config_file:
        return {}

    try:
        with open(config_file) as f:
            conf: Dict = json.load(f)
            return conf
    except (OSError, ValueError) as e:
        # In the case of a legacy `.dockercfg` file, we won't
        # be able to load any JSON data.
        log.debug(e)

    log.debug("All parsing attempts failed - returning empty config")
    return {}


def resolve_repository_name(repo_name: str) -> Tuple[str, str]:
    if "://" in repo_name:
        raise InvalidRepositoryError(
            f"Repository name cannot contain a scheme ({repo_name})"
        )

    index_name, remote_name = split_repo_name(repo_name)
    if index_name[0] == "-" or index_name[-1] == "-":
        raise InvalidRepositoryError(
            f"Invalid index name ({index_name}). Cannot begin or end with a hyphen."
        )
    return resolve_index_name(index_name), remote_name


def resolve_index_name(index_name: str) -> str:
    index_name = convert_to_hostname(index_name)
    if index_name == "index." + INDEX_NAME:
        index_name = INDEX_NAME
    return index_name


def split_repo_name(repo_name: str) -> Tuple[str, str]:
    parts = repo_name.split("/", 1)
    if len(parts) == 1 or (
        "." not in parts[0] and ":" not in parts[0] and parts[0] != "localhost"
    ):
        # This is a docker index repo (ex: username/foobar or ubuntu)
        return INDEX_NAME, repo_name
    return parts[0], parts[1]


def get_credential_store(authconfig: Dict, registry: str) -> Optional[str]:
    if not isinstance(authconfig, AuthConfig):
        authconfig = AuthConfig(authconfig)
    return authconfig.get_credential_store(registry)


class AuthConfig(dict):
    def __init__(self, dct: Dict, credstore_env: Optional[Mapping] = None) -> None:
        super().__init__(dct)
        if "auths" not in dct:
            dct["auths"] = {}
        self.update(dct)
        self._credstore_env = credstore_env
        self._stores: Dict[str, dockerpycreds.Store] = dict()

    @classmethod
    def parse_auth(
        cls,
        entries: Dict[str, Dict[str, Any]],
        raise_on_error: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Parse authentication entries.

        Args:
          entries:        Dict of authentication entries.
          raise_on_error: If set to true, an invalid format will raise
                          InvalidConfigFileError
        Returns:
          Authentication registry.
        """
        conf = {}
        for registry, entry in entries.items():
            if not isinstance(entry, dict):
                log.debug(f"Config entry for key {registry} is not auth config")  # type: ignore
                # We sometimes fall back to parsing the whole config as if it
                # was the auth config by itself, for legacy purposes. In that
                # case, we fail silently and return an empty conf if any of the
                # keys is not formatted properly.
                if raise_on_error:
                    raise InvalidConfigFileError(
                        f"Invalid configuration for registry {registry}"
                    )
                return {}
            if "identitytoken" in entry:
                log.debug(f"Found an IdentityToken entry for registry {registry}")
                conf[registry] = {"IdentityToken": entry["identitytoken"]}
                continue  # Other values are irrelevant if we have a token

            if "auth" not in entry:
                # Starting with engine v1.11 (API 1.23), an empty dictionary is
                # a valid value in the auth's config.
                # https://github.com/docker/compose/issues/3265
                log.debug(
                    f"Auth data for {registry} is absent. Client might be using a "
                    "credentials store instead."
                )
                conf[registry] = {}
                continue

            username, password = decode_auth(entry["auth"])
            log.debug(
                f"Found entry (registry={repr(registry)}, username={repr(username)})"
            )

            conf[registry] = {
                "username": username,
                "password": password,
                "email": entry.get("email"),
                "serveraddress": registry,
            }
        return conf

    @classmethod
    def load_config(
        cls,
        config_path: Optional[str],
        config_dict: Optional[Dict[str, Any]],
        credstore_env: Optional[Mapping] = None,
    ) -> "AuthConfig":
        """Load authentication data from a Docker configuration file.

        If the config_path is not passed in it looks for a configuration file in the
        root directory.

        Lookup priority:
            explicit config_path parameter > DOCKER_CONFIG environment
            variable > ~/.docker/config.json > ~/.dockercfg.
        """
        if not config_dict:
            config_file = find_config_file(config_path)

            if not config_file:
                return cls({}, credstore_env)
            try:
                with open(config_file) as f:
                    config_dict = json.load(f)
            except (OSError, KeyError, ValueError) as e:
                # Likely missing new Docker config file, or it's in an
                # unknown format, continue to attempt to read old location
                # and format.
                log.debug(e)
                return cls(_load_legacy_config(config_file), credstore_env)

        res = {}
        assert isinstance(config_dict, Dict)  # worship mypy
        if config_dict.get("auths"):
            log.debug("Found 'auths' section")
            res.update(
                {"auths": cls.parse_auth(config_dict.pop("auths"), raise_on_error=True)}
            )
        if config_dict.get("credsStore"):
            log.debug("Found 'credsStore' section")
            res.update({"credsStore": config_dict.pop("credsStore")})
        if config_dict.get("credHelpers"):
            log.debug("Found 'credHelpers' section")
            res.update({"credHelpers": config_dict.pop("credHelpers")})
        if res:
            return cls(res, credstore_env)

        log.debug(
            "Couldn't find auth-related section ; attempting to interpret "
            "as auth-only file"
        )
        return cls({"auths": cls.parse_auth(config_dict)}, credstore_env)

    @property
    def auths(self) -> Dict[str, Dict[str, Any]]:
        return self.get("auths", {})  # type: ignore

    @property
    def creds_store(self) -> Optional[str]:
        return self.get("credsStore", None)  # type: ignore

    @property
    def cred_helpers(self) -> Dict:
        return self.get("credHelpers", {})  # type: ignore

    @property
    def is_empty(self) -> bool:
        return not self.auths and not self.creds_store and not self.cred_helpers

    def resolve_authconfig(
        self, registry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Return the authentication data for a specific registry.

        As with the Docker client, legacy entries in the config with full URLs are
        stripped down to hostnames before checking for a match. Returns None if no match
        was found.
        """
        if self.creds_store or self.cred_helpers:
            store_name = self.get_credential_store(registry)
            if store_name is not None:
                log.debug(f"Using credentials store {store_name!r}")
                cfg = self._resolve_authconfig_credstore(registry, store_name)
                if cfg is not None:
                    return cfg
                log.debug("No entry in credstore - fetching from auth dict")

        # Default to the public index server
        registry = resolve_index_name(registry) if registry else INDEX_NAME
        log.debug(f"Looking for auth entry for {repr(registry)}")

        if registry in self.auths:
            log.debug(f"Found {repr(registry)}")
            return self.auths[registry]

        for key, conf in self.auths.items():
            if resolve_index_name(key) == registry:
                log.debug(f"Found {repr(key)}")
                return conf

        log.debug("No entry found")
        return None

    def _resolve_authconfig_credstore(
        self, registry: Optional[str], credstore_name: str
    ) -> Optional[Dict[str, Any]]:
        if not registry or registry == INDEX_NAME:
            # The ecosystem is a little schizophrenic with recker.io VS
            # docker.io - in that case, it seems the full URL is necessary.
            registry = INDEX_URL
        log.debug(f"Looking for auth entry for {repr(registry)}")
        store = self._get_store_instance(credstore_name)
        try:
            data = store.get(registry)
            res = {
                "ServerAddress": registry,
            }
            if data["Username"] == TOKEN_USERNAME:
                res["IdentityToken"] = data["Secret"]
            else:
                res.update({"Username": data["Username"], "Password": data["Secret"]})
            return res
        except (dockerpycreds.CredentialsNotFound, ValueError):
            log.debug("No entry found")
            return None
        except dockerpycreds.StoreError as e:
            raise DockerError(f"Credentials store error: {repr(e)}")

    def _get_store_instance(self, name: str) -> "dockerpycreds.Store":
        if name not in self._stores:
            self._stores[name] = dockerpycreds.Store(
                name, environment=self._credstore_env
            )
        return self._stores[name]

    def get_credential_store(self, registry: Optional[str]) -> Optional[str]:
        if not registry or registry == INDEX_NAME:
            registry = INDEX_URL

        return self.cred_helpers.get(registry) or self.creds_store

    def get_all_credentials(self) -> Dict[str, Dict[str, Any]]:
        auth_data = self.auths.copy()
        if self.creds_store:
            # Retrieve all credentials from the default store
            store = self._get_store_instance(self.creds_store)
            for k in store.list().keys():
                auth_data[k] = self._resolve_authconfig_credstore(k, self.creds_store)  # type: ignore

        # credHelpers entries take priority over all others
        for reg, store_name in self.cred_helpers.items():
            auth_data[reg] = self._resolve_authconfig_credstore(reg, store_name)  # type: ignore

        return auth_data

    def add_auth(self, reg: str, data: Dict[str, Any]) -> None:
        self["auths"][reg] = data


def resolve_authconfig(
    authconfig: Dict,
    registry: Optional[str] = None,
    credstore_env: Optional[Mapping] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(authconfig, AuthConfig):
        authconfig = AuthConfig(authconfig, credstore_env)
    return authconfig.resolve_authconfig(registry)


def convert_to_hostname(url: str) -> str:
    return url.replace("http://", "").replace("https://", "").split("/", 1)[0]


def decode_auth(auth: Union[str, bytes]) -> Tuple[str, str]:
    if isinstance(auth, str):
        auth = auth.encode("ascii")
    s = base64.b64decode(auth)
    login, pwd = s.split(b":", 1)
    return login.decode("utf8"), pwd.decode("utf8")


def parse_auth(
    entries: Dict, raise_on_error: bool = False
) -> Dict[str, Dict[str, Any]]:
    """Parse authentication entries.

    Args:
      entries:        Dict of authentication entries.
      raise_on_error: If set to true, an invalid format will raise
                      InvalidConfigFileError
    Returns:
      Authentication registry.
    """
    return AuthConfig.parse_auth(entries, raise_on_error)


def load_config(
    config_path: Optional[str] = None,
    config_dict: Optional[Dict[str, Any]] = None,
    credstore_env: Optional[Mapping] = None,
) -> AuthConfig:
    return AuthConfig.load_config(config_path, config_dict, credstore_env)


def _load_legacy_config(
    config_file: str,
) -> Dict[str, Dict[str, Union[str, Dict[str, str]]]]:
    log.debug("Attempting to parse legacy auth file format")
    try:
        data = []
        with open(config_file) as f:
            for line in f.readlines():
                data.append(line.strip().split(" = ")[1])
            if len(data) < 2:
                # Not enough data
                raise InvalidConfigFileError("Invalid or empty configuration file!")

        username, password = decode_auth(data[0])
        return {
            "auths": {
                INDEX_NAME: {
                    "username": username,
                    "password": password,
                    "email": data[1],
                    "serveraddress": INDEX_URL,
                }
            }
        }
    except Exception as e:
        log.debug(e)

    log.debug("All parsing attempts failed - returning empty config")
    return {}
