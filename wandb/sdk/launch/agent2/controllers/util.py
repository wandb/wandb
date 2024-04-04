from ..controller import LaunchControllerConfig


def parse_max_concurrency(config: LaunchControllerConfig, default: int) -> int:
    max_concurrency = config["jobset_metadata"]["@max_concurrency"]
    if max_concurrency is None or max_concurrency == "auto":
        return default
    else:
        try:
            return int(max_concurrency)
        except ValueError:
            raise ValueError(
                f"Invalid value for max_concurrency: {max_concurrency}. Must be an integer or 'auto'"
            )
