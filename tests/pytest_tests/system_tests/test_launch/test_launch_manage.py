"""System tests for the `wandb.sdk.launch.inputs.manage` module.

These tests execute the real user flow exposed by the
`wandb.sdk.launch.inputs.manage` module.
"""

import os
import time

import pytest
import wandb
import wandb.env
import yaml
from wandb.sdk import launch


@pytest.fixture
def test_config():
    return {
        "key1": 1,
        "key2": {
            "key3": "hello",
            "key4": {
                "key5": "world",
                "key6": {
                    "key7": 1,
                    "key8": 2,
                },
            },
        },
    }


@pytest.mark.wandb_core_only
def test_manage_config_file(
    test_settings,
    wandb_init,
    tmp_path,
    test_config,
    monkeypatch,
    relay_server,
):
    """Test that calling `manage_config_file` has the expected side effects.

    If `manage_config_file` is called and a job is created then the run should
    have the config file saved in its files and the job should have the config
    file schema.
    """
    monkeypatch.chdir(tmp_path)
    config_str = yaml.dump(test_config)

    (tmp_path / "config.yaml").write_text(config_str)
    settings = test_settings()
    settings.update(
        {
            "program_relpath": "./blah/test_program.py",
            "git_remote_url": "https://github.com/test/repo",
            "git_commit": "asdasdasdasd",
        }
    )
    with relay_server():
        with wandb_init(settings=settings) as run:
            launch.manage_config_file(
                "config.yaml",
                include=["key2"],
                exclude=["key2.key4.key6.key8", "key2.key3"],
            )
            run.log({"test": 1})

        api = wandb.Api()
        run_api_object = api.run(run.path)
        poll = 1
        while poll < 8:
            file = run_api_object.file("configs/config.yaml")
            if file.size == len(config_str):
                break
            time.sleep(poll)
            poll *= 2
            run_api_object.update()
        else:
            raise ValueError("File was not uploaded")

        job_artifact = [*run_api_object.used_artifacts()][0]
        assert job_artifact.metadata == {
            "input_types": {
                "files": {
                    "config.yaml": {
                        "params": {
                            "type_map": {
                                "key2": {
                                    "params": {
                                        "type_map": {
                                            "key4": {
                                                "params": {
                                                    "type_map": {
                                                        "key5": {"wb_type": "string"},
                                                        "key6": {
                                                            "params": {
                                                                "type_map": {
                                                                    "key7": {
                                                                        "wb_type": "number"
                                                                    }
                                                                }
                                                            },
                                                            "wb_type": "typedDict",
                                                        },
                                                    }
                                                },
                                                "wb_type": "typedDict",
                                            }
                                        }
                                    },
                                    "wb_type": "typedDict",
                                }
                            }
                        },
                        "wb_type": "typedDict",
                    }
                },
                "@wandb.config": {"params": {"type_map": {}}, "wb_type": "typedDict"},
            },
            "output_types": {"wb_type": "unknown"},
        }


@pytest.mark.wandb_core_only
def test_manage_wandb_config(
    test_settings,
    wandb_init,
    test_config,
):
    """Test that calling `manage_wandb_config` has the expected side effects.

    If `manage_wandb_config` is called and a job is created then the job should
    have the wandb config schema saved in its metadata.
    """
    settings = test_settings()
    settings.update(
        {
            "program_relpath": "./blah/test_program.py",
            "git_remote_url": "https://github.com/test/repo",
            "git_commit": "asdasdasdasd",
        }
    )
    with wandb_init(settings=settings, config=test_config) as run:
        launch.manage_wandb_config(
            include=["key2"], exclude=["key2.key4.key6.key8", "key2.key3"]
        )
        run.log({"test": 1})

    api = wandb.Api()
    run_api_object = api.run(run.path)
    job_artifact = [*run_api_object.used_artifacts()][0]
    assert job_artifact.metadata == {
        "input_types": {
            "@wandb.config": {
                "params": {
                    "type_map": {
                        "key2": {
                            "params": {
                                "type_map": {
                                    "key4": {
                                        "params": {
                                            "type_map": {
                                                "key5": {"wb_type": "string"},
                                                "key6": {
                                                    "params": {
                                                        "type_map": {
                                                            "key7": {
                                                                "wb_type": "number"
                                                            }
                                                        }
                                                    },
                                                    "wb_type": "typedDict",
                                                },
                                            }
                                        },
                                        "wb_type": "typedDict",
                                    }
                                }
                            },
                            "wb_type": "typedDict",
                        }
                    }
                },
                "wb_type": "typedDict",
            }
        },
        "output_types": {"wb_type": "unknown"},
    }
