from click.testing import CliRunner
import pytest
from wandb.history import History


@pytest.fixture
def history():
    with CliRunner().isolated_filesystem():
        yield History("wandb-history.jsonl")