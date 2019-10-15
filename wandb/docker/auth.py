# most of this taken from: https://github.com/docker/docker-py/blob/master/docker/auth.py
import base64
import json
import logging
import dockerpycreds
import six
import json
import logging
import os
import sys
import platform

IS_WINDOWS_PLATFORM = (platform.system() == 'Windows')
DOCKER_CONFIG_FILENAME = os.path.join('.docker', 'config.json')
LEGACY_DOCKER_CONFIG_FILENAME = '.dockercfg'
INDEX_NAME = 'docker.io'
INDEX_URL = 'https://index.{0}/v1/'.format(INDEX_NAME)
TOKEN_USERNAME = '<token>'

log = logging.getLogger(__name__)


class DockerException(Exception):
    """
    A base class from which all other exceptions inherit.
    If you want to catch all errors that the Docker SDK might raise,
    catch this base exception.
    """


class InvalidConfigFile(DockerException):
    pass


class InvalidRepository(DockerException):
    pass


def find_config_file(config_path=None):
    paths = list(filter(None, [
        config_path,  # 1
        config_path_from_environment(),  # 2
        os.path.join(home_dir(), DOCKER_CONFIG_FILENAME),  # 3
        os.path.join(home_dir(), LEGACY_DOCKER_CONFIG_FILENAME),  # 4
    ]))

    log.debug("Trying paths: {0}".format(repr(paths)))

    for path in paths:
        if os.path.exists(path):
            log.debug("Found file at path: {0}".format(path))
            return path

    log.debug("No config file found")

    return None


def config_path_from_environment():
    config_dir = os.environ.get('DOCKER_CONFIG')
    if not config_dir:
        return None
    return os.path.join(config_dir, os.path.basename(DOCKER_CONFIG_FILENAME))


def home_dir():
    """
    Get the user's home directory, using the same logic as the Docker Engine
    client - use %USERPROFILE% on Windows, $HOME/getuid on POSIX.
    """
    if IS_WINDOWS_PLATFORM:
        return os.environ.get('USERPROFILE', '')
    else:
        return os.path.expanduser('~')


def load_general_config(config_path=None):
    config_file = find_config_file(config_path)

    if not config_file:
        return {}

    try:
        with open(config_file) as f:
            return json.load(f)
    except (IOError, ValueError) as e:
        # In the case of a legacy `.dockercfg` file, we won't
        # be able to load any JSON data.
        log.debug(e)

    log.debug("All parsing attempts failed - returning empty config")
    return {}


def resolve_repository_name(repo_name):
    if '://' in repo_name:
        raise InvalidRepository(
            'Repository name cannot contain a scheme ({0})'.format(repo_name)
        )

    index_name, remote_name = split_repo_name(repo_name)
    if index_name[0] == '-' or index_name[-1] == '-':
        raise InvalidRepository(
            'Invalid index name ({0}). Cannot begin or end with a'
            ' hyphen.'.format(index_name)
        )
    return resolve_index_name(index_name), remote_name


def resolve_index_name(index_name):
    index_name = convert_to_hostname(index_name)
    if index_name == 'index.' + INDEX_NAME:
        index_name = INDEX_NAME
    return index_name


def split_repo_name(repo_name):
    parts = repo_name.split('/', 1)
    if len(parts) == 1 or (
        '.' not in parts[0] and ':' not in parts[0] and parts[0] != 'localhost'
    ):
        # This is a docker index repo (ex: username/foobar or ubuntu)
        return INDEX_NAME, repo_name
    return tuple(parts)


def get_credential_store(authconfig, registry):
    if not isinstance(authconfig, AuthConfig):
        authconfig = AuthConfig(authconfig)
    return authconfig.get_credential_store(registry)


class AuthConfig(dict):
    def __init__(self, dct, credstore_env=None):
        if 'auths' not in dct:
            dct['auths'] = {}
        self.update(dct)
        self._credstore_env = credstore_env
        self._stores = {}

    @classmethod
    def parse_auth(cls, entries, raise_on_error=False):
        """
        Parses authentication entries
        Args:
          entries:        Dict of authentication entries.
          raise_on_error: If set to true, an invalid format will raise
                          InvalidConfigFile
        Returns:
          Authentication registry.
        """

        conf = {}
        for registry, entry in six.iteritems(entries):
            if not isinstance(entry, dict):
                log.debug(
                    'Config entry for key {0} is not auth config'.format(
                        registry
                    )
                )
                # We sometimes fall back to parsing the whole config as if it
                # was the auth config by itself, for legacy purposes. In that
                # case, we fail silently and return an empty conf if any of the
                # keys is not formatted properly.
                if raise_on_error:
                    raise InvalidConfigFile(
                        'Invalid configuration for registry {0}'.format(
                            registry
                        )
                    )
                return {}
            if 'identitytoken' in entry:
                log.debug(
                    'Found an IdentityToken entry for registry {0}'.format(
                        registry
                    )
                )
                conf[registry] = {
                    'IdentityToken': entry['identitytoken']
                }
                continue  # Other values are irrelevant if we have a token

            if 'auth' not in entry:
                # Starting with engine v1.11 (API 1.23), an empty dictionary is
                # a valid value in the auths config.
                # https://github.com/docker/compose/issues/3265
                log.debug(
                    'Auth data for {0} is absent. Client might be using a '
                    'credentials store instead.'.format(registry)
                )
                conf[registry] = {}
                continue

            username, password = decode_auth(entry['auth'])
            log.debug(
                'Found entry (registry={0}, username={1})'
                .format(repr(registry), repr(username))
            )

            conf[registry] = {
                'username': username,
                'password': password,
                'email': entry.get('email'),
                'serveraddress': registry,
            }
        return conf

    @classmethod
    def load_config(cls, config_path, config_dict, credstore_env=None):
        """
        Loads authentication data from a Docker configuration file in the given
        root directory or if config_path is passed use given path.
        Lookup priority:
            explicit config_path parameter > DOCKER_CONFIG environment
            variable > ~/.docker/config.json > ~/.dockercfg
        """

        if not config_dict:
            config_file = find_config_file(config_path)

            if not config_file:
                return cls({}, credstore_env)
            try:
                with open(config_file) as f:
                    config_dict = json.load(f)
            except (IOError, KeyError, ValueError) as e:
                # Likely missing new Docker config file or it's in an
                # unknown format, continue to attempt to read old location
                # and format.
                log.debug(e)
                return cls(_load_legacy_config(config_file), credstore_env)

        res = {}
        if config_dict.get('auths'):
            log.debug("Found 'auths' section")
            res.update({
                'auths': cls.parse_auth(
                    config_dict.pop('auths'), raise_on_error=True
                )
            })
        if config_dict.get('credsStore'):
            log.debug("Found 'credsStore' section")
            res.update({'credsStore': config_dict.pop('credsStore')})
        if config_dict.get('credHelpers'):
            log.debug("Found 'credHelpers' section")
            res.update({'credHelpers': config_dict.pop('credHelpers')})
        if res:
            return cls(res, credstore_env)

        log.debug(
            "Couldn't find auth-related section ; attempting to interpret "
            "as auth-only file"
        )
        return cls({'auths': cls.parse_auth(config_dict)}, credstore_env)

    @property
    def auths(self):
        return self.get('auths', {})

    @property
    def creds_store(self):
        return self.get('credsStore', None)

    @property
    def cred_helpers(self):
        return self.get('credHelpers', {})

    @property
    def is_empty(self):
        return (
            not self.auths and not self.creds_store and not self.cred_helpers
        )

    def resolve_authconfig(self, registry=None):
        """
        Returns the authentication data from the given auth configuration for a
        specific registry. As with the Docker client, legacy entries in the
        config with full URLs are stripped down to hostnames before checking
        for a match. Returns None if no match was found.
        """

        if self.creds_store or self.cred_helpers:
            store_name = self.get_credential_store(registry)
            if store_name is not None:
                log.debug(
                    'Using credentials store "{0}"'.format(store_name)
                )
                cfg = self._resolve_authconfig_credstore(registry, store_name)
                if cfg is not None:
                    return cfg
                log.debug('No entry in credstore - fetching from auth dict')

        # Default to the public index server
        registry = resolve_index_name(registry) if registry else INDEX_NAME
        log.debug("Looking for auth entry for {0}".format(repr(registry)))

        if registry in self.auths:
            log.debug("Found {0}".format(repr(registry)))
            return self.auths[registry]

        for key, conf in six.iteritems(self.auths):
            if resolve_index_name(key) == registry:
                log.debug("Found {0}".format(repr(key)))
                return conf

        log.debug("No entry found")
        return None

    def _resolve_authconfig_credstore(self, registry, credstore_name):
        if not registry or registry == INDEX_NAME:
            # The ecosystem is a little schizophrenic with recker.io VS
            # docker.io - in that case, it seems the full URL is necessary.
            registry = INDEX_URL
        log.debug("Looking for auth entry for {0}".format(repr(registry)))
        store = self._get_store_instance(credstore_name)
        try:
            data = store.get(registry)
            res = {
                'ServerAddress': registry,
            }
            if data['Username'] == TOKEN_USERNAME:
                res['IdentityToken'] = data['Secret']
            else:
                res.update({
                    'Username': data['Username'],
                    'Password': data['Secret'],
                })
            return res
        except dockerpycreds.CredentialsNotFound:
            log.debug('No entry found')
            return None
        except dockerpycreds.StoreError as e:
            raise DockerException(
                'Credentials store error: {0}'.format(repr(e))
            )

    def _get_store_instance(self, name):
        if name not in self._stores:
            self._stores[name] = dockerpycreds.Store(
                name, environment=self._credstore_env
            )
        return self._stores[name]

    def get_credential_store(self, registry):
        if not registry or registry == INDEX_NAME:
            registry = INDEX_URL

        return self.cred_helpers.get(registry) or self.creds_store

    def get_all_credentials(self):
        auth_data = self.auths.copy()
        if self.creds_store:
            # Retrieve all credentials from the default store
            store = self._get_store_instance(self.creds_store)
            for k in store.list().keys():
                auth_data[k] = self._resolve_authconfig_credstore(
                    k, self.creds_store
                )

        # credHelpers entries take priority over all others
        for reg, store_name in self.cred_helpers.items():
            auth_data[reg] = self._resolve_authconfig_credstore(
                reg, store_name
            )

        return auth_data

    def add_auth(self, reg, data):
        self['auths'][reg] = data


def resolve_authconfig(authconfig, registry=None, credstore_env=None):
    if not isinstance(authconfig, AuthConfig):
        authconfig = AuthConfig(authconfig, credstore_env)
    return authconfig.resolve_authconfig(registry)


def convert_to_hostname(url):
    return url.replace('http://', '').replace('https://', '').split('/', 1)[0]


def decode_auth(auth):
    if isinstance(auth, six.string_types):
        auth = auth.encode('ascii')
    s = base64.b64decode(auth)
    login, pwd = s.split(b':', 1)
    return login.decode('utf8'), pwd.decode('utf8')


def parse_auth(entries, raise_on_error=False):
    """
    Parses authentication entries
    Args:
      entries:        Dict of authentication entries.
      raise_on_error: If set to true, an invalid format will raise
                      InvalidConfigFile
    Returns:
      Authentication registry.
    """

    return AuthConfig.parse_auth(entries, raise_on_error)


def load_config(config_path=None, config_dict=None, credstore_env=None):
    return AuthConfig.load_config(config_path, config_dict, credstore_env)


def _load_legacy_config(config_file):
    log.debug("Attempting to parse legacy auth file format")
    try:
        data = []
        with open(config_file) as f:
            for line in f.readlines():
                data.append(line.strip().split(' = ')[1])
            if len(data) < 2:
                # Not enough data
                raise InvalidConfigFile(
                    'Invalid or empty configuration file!'
                )

        username, password = decode_auth(data[0])
        return {'auths': {
            INDEX_NAME: {
                'username': username,
                'password': password,
                'email': data[1],
                'serveraddress': INDEX_URL,
            }
        }}
    except Exception as e:
        log.debug(e)
        pass

    log.debug("All parsing attempts failed - returning empty config")
    return {}
