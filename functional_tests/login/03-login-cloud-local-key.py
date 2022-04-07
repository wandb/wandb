#!/usr/bin/env python
"""WB-8618: warn the user if they are using a local key to log in to cloud"""

import random
import string

import pytest
import wandb
import wandb.errors


# function to generate a random alphanumeric key of 40 chars
def random_key():
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(40))


if __name__ == "__main__":
    # api_key starts with "local", but base_url points to cloud
    with pytest.raises(wandb.errors.UsageError) as e:
        wandb.login(key=f"local-{random_key()}")
        assert (
            "Attempting to use a local API key to connect to https://api.wandb.ai" in str(e.value)
        )

    # check that this logic does not apply if base_url is not cloud
    assert wandb.login(key=f"local-{random_key()}", host="https://api.wandb.test")
