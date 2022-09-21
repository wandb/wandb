import sys


def test_path_is_unchanged():
    # Ideally we would compare directly to the user's starting path,
    # but that seems to be mutiliated with tox. So, we check for known
    # leaks.
    import wandb  # noqa: F401

    for item in sys.path:
        assert "wandb/vendor" not in item
