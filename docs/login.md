---
title: Login
---

<a name="wandb.sdk.wandb_login"></a>
# wandb.sdk.wandb\_login

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L3)

Log in to Weights & Biases, authenticating your machine to log data to your
account.

<a name="wandb.sdk.wandb_login.login"></a>
#### login

```python
login(anonymous=None, key=None, relogin=None, host=None, force=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L22)

Log in to W&B.

**Arguments**:

- `anonymous` _string, optional_ - Can be "must", "allow", or "never".
If set to "must" we'll always login anonymously, if set to
"allow" we'll only create an anonymous user if the user
isn't already logged in.
- `key` _string, optional_ - authentication key.
- `relogin` _bool, optional_ - If true, will re-prompt for API key.
- `host` _string, optional_ - The host to connect to.


**Returns**:

- `bool` - if key is configured


**Raises**:

UsageError - if api_key can not configured and no tty

<a name="wandb.sdk.wandb_login._WandbLogin"></a>
## \_WandbLogin Objects

```python
class _WandbLogin(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L45)

<a name="wandb.sdk.wandb_login._WandbLogin.__init__"></a>
#### \_\_init\_\_

```python
 | __init__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L46)

<a name="wandb.sdk.wandb_login._WandbLogin.setup"></a>
#### setup

```python
 | setup(kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L54)

<a name="wandb.sdk.wandb_login._WandbLogin.is_apikey_configured"></a>
#### is\_apikey\_configured

```python
 | is_apikey_configured()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L69)

<a name="wandb.sdk.wandb_login._WandbLogin.set_backend"></a>
#### set\_backend

```python
 | set_backend(backend)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L72)

<a name="wandb.sdk.wandb_login._WandbLogin.set_silent"></a>
#### set\_silent

```python
 | set_silent(silent)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L75)

<a name="wandb.sdk.wandb_login._WandbLogin.login"></a>
#### login

```python
 | login()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L78)

<a name="wandb.sdk.wandb_login._WandbLogin.login_display"></a>
#### login\_display

```python
 | login_display()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L90)

<a name="wandb.sdk.wandb_login._WandbLogin.configure_api_key"></a>
#### configure\_api\_key

```python
 | configure_api_key(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L110)

<a name="wandb.sdk.wandb_login._WandbLogin.update_session"></a>
#### update\_session

```python
 | update_session(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L124)

<a name="wandb.sdk.wandb_login._WandbLogin.prompt_api_key"></a>
#### prompt\_api\_key

```python
 | prompt_api_key()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L135)

<a name="wandb.sdk.wandb_login._WandbLogin.propogate_login"></a>
#### propogate\_login

```python
 | propogate_login()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_login.py#L148)

