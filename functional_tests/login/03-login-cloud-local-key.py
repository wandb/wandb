#!/usr/bin/env python
"""WB-8618: warn the user if they are using a local key to login to cloud"""

import pytest
import wandb
import wandb.errors


if __name__ == "__main__":
    with pytest.raises(wandb.errors.UsageError) as e:
        wandb.login(key="local1234567890")
        assert (
            "Attempting to use a local API key to connect to https://api.wandb.ai" in str(e.value)
        )
