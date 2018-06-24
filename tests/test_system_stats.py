import pytest
from wandb.stats import SystemStats
from click.testing import CliRunner
import wandb
import json


@pytest.fixture
def api():
    return wandb.apis.InternalApi()


@pytest.fixture
def stats(api):
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run.from_environment_or_defaults()
        yield SystemStats(run, api)


def test_defaults(stats):
    stats.shutdown()
    print(stats.stats().keys())
    assert sorted(stats.stats().keys()) == sorted(
        ['cpu', 'memory', 'network', 'disk', 'proc.memory.rssMB', 'proc.memory.availableMB', 'proc.memory.percent', 'proc.cpu.threads'])
    assert stats.sample_rate_seconds == 2
    assert stats.samples_to_average == 15


def test_dynamic(stats, api):
    api.dynamic_settings["system_sample_seconds"] = 1
    api.dynamic_settings["system_samples"] = 2
    assert stats.sample_rate_seconds == 1
    assert stats.samples_to_average == 2


def test_min_max(stats, api):
    api.dynamic_settings["system_sample_seconds"] = 0.25
    api.dynamic_settings["system_samples"] = 300
    assert stats.sample_rate_seconds == 0.5
    assert stats.samples_to_average == 30
    api.dynamic_settings["system_samples"] = 1
    assert stats.samples_to_average == 2
