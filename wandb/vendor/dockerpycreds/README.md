# docker-pycreds

[![CircleCI](https://circleci.com/gh/shin-/dockerpy-creds/tree/master.svg?style=svg)](https://circleci.com/gh/shin-/dockerpy-creds/tree/master)

Python bindings for the docker credentials store API

## Credentials store info

[Docker documentation page](https://docs.docker.com/engine/reference/commandline/login/#/credentials-store)

## Requirements

On top of the dependencies in `requirements.txt`, the `docker-credential`
executable for the platform must be installed on the user's system.

## API usage

```python

import dockerpycreds

store = dockerpycreds.Store('secretservice')
store.store(
    server='https://index.docker.io/v1/', username='johndoe',
    secret='hunter2'
)

print(store.list())

print(store.get('https://index.docker.io/v1/'))


store.erase('https://index.docker.io/v1/')
```
