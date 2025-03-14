import logging

if __name__ == "__main__":
    logger = logging.getLogger("wandb")

    # logging.lastResort by default outputs to stderr. Check that this is true.
    logger.warning("lastResort (before configuring)")

    # Import wandb to trigger wb_logging.configure_wandb_logger().
    import wandb  # noqa: F401

    # configure_wandb_logger() should prevent lastResort from being used for
    # messages logged to the "wandb" logger.
    logger.warning("lastResort (after configuring -- not output)")

    # Another way the message can be suppressed is if the "wandb" logger's level
    # is set above WARNING. Verify that this isn't the case.
    logger.addHandler(logging.StreamHandler())
    logger.warning("stream handler (after configuring)")
