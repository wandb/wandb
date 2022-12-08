import os
import random
import sys

import pytest
import six
from distutils.spawn import find_executable

from dockerpycreds import (
    CredentialsNotFound, Store, StoreError, DEFAULT_LINUX_STORE,
    DEFAULT_OSX_STORE
)


class TestStore(object):
    def teardown_method(self):
        for server in self.tmp_keys:
            try:
                self.store.erase(server)
            except StoreError:
                pass

    def setup_method(self):
        self.tmp_keys = []
        if sys.platform.startswith('linux'):
            if find_executable('docker-credential-' + DEFAULT_LINUX_STORE):
                self.store = Store(DEFAULT_LINUX_STORE)
            elif find_executable('docker-credential-pass'):
                self.store = Store('pass')
            else:
                raise Exception('No supported docker-credential store in PATH')
        elif sys.platform.startswith('darwin'):
            self.store = Store(DEFAULT_OSX_STORE)

    def get_random_servername(self):
        res = 'pycreds_test_{:x}'.format(random.getrandbits(32))
        self.tmp_keys.append(res)
        return res

    def test_store_and_get(self):
        key = self.get_random_servername()
        self.store.store(server=key, username='user', secret='pass')
        data = self.store.get(key)
        assert data == {
            'ServerURL': key,
            'Username': 'user',
            'Secret': 'pass'
        }

    def test_get_nonexistent(self):
        key = self.get_random_servername()
        with pytest.raises(CredentialsNotFound):
            self.store.get(key)

    def test_store_and_erase(self):
        key = self.get_random_servername()
        self.store.store(server=key, username='user', secret='pass')
        self.store.erase(key)
        with pytest.raises(CredentialsNotFound):
            self.store.get(key)

    def test_unicode_strings(self):
        key = self.get_random_servername()
        key = six.u(key)
        self.store.store(server=key, username='user', secret='pass')
        data = self.store.get(key)
        assert data
        self.store.erase(key)
        with pytest.raises(CredentialsNotFound):
            self.store.get(key)

    def test_list(self):
        names = (self.get_random_servername(), self.get_random_servername())
        self.store.store(names[0], username='sakuya', secret='izayoi')
        self.store.store(names[1], username='reimu', secret='hakurei')
        data = self.store.list()
        assert names[0] in data
        assert data[names[0]] == 'sakuya'
        assert names[1] in data
        assert data[names[1]] == 'reimu'

    def test_execute_with_env_override(self):
        self.store.exe = 'env'
        self.store.environment = {'FOO': 'bar'}
        data = self.store._execute('--null', '')
        assert b'\0FOO=bar\0' in data
        assert 'FOO' not in os.environ
