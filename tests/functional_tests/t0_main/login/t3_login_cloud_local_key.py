#!/usr/bin/env python
"""WB-8618: warn the user if they are using a local key to log in to cloud"""

import pytest
import wandb
import wandb.errors

if __name__ == "__main__":
    # api_key starts with "local", but base_url points to cloud
    with pytest.raises(wandb.errors.UsageError) as e:
        wandb.login(key="local-87eLxjoRhY6u2ofg63NAJo7rVYHZo4NGACOvpSsF}")
        assert (
            "Attempting to use a local API key to connect to https://api.wandb.ai"
            in str(e.value)
        )

    # check that this logic does not apply if base_url is not cloud
    assert wandb.login(
        key="local-87eLxjoRhY6u2ofg63NAJo7rVYHZo4NGACOvpSsF",
        host="https://api.wandb.test",
    )
