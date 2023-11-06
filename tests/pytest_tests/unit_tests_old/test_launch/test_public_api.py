import wandb


def test_from_path(mock_server, api):
    sweep = api.from_path("test/test/sweeps/test")
    assert isinstance(sweep, wandb.apis.public.Sweep)


def test_project_sweeps(mock_server, api):
    project = api.from_path("test")
    psweeps = project.sweeps()
    assert len(psweeps) == 1
    assert psweeps[0].id == "testid"
    assert psweeps[0].name == "testname"

    no_sweeps_project = api.from_path("testnosweeps")
    nspsweeps = no_sweeps_project.sweeps()
    assert len(nspsweeps) == 0


def test_sweep(runner, mock_server, api):
    sweep = api.sweep("test/test/test")
    assert sweep.entity == "test"
    assert sweep.best_run().name == "beast-bug-33"
    assert sweep.url == "https://wandb.ai/test/test/sweeps/test"
    assert sweep.state in ["running", "finished"]
    assert str(sweep) == "<Sweep test/test/test (running)>"


def test_to_html(mock_server, api):
    sweep = api.from_path("test/test/sweeps/test")
    assert "test/test/sweeps/test?jupyter=true" in sweep.to_html()
