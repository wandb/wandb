import datetime
import io
import os

import wandb.run_manager
from wandb.apis import internal
from wandb.wandb_run import Run
from click.testing import CliRunner


def test_check_update_available_equal(request_mocker, capsys):
    "Test update availability in different cases."
    test_cases = [
        ('0.8.10', '0.8.10', False),
        ('0.8.9', '0.8.10', True),
        ('0.8.11', '0.8.10', False),
        ('1.0.0', '2.0.0', True),
        ('0.4.5', '0.4.5a5', False),
        ('0.4.5', '0.4.3b2', False),
        ('0.4.5', '0.4.6b2', True),
        ('0.4.5.alpha', '0.4.4', False),
        ('0.4.5.alpha', '0.4.5', True),
        ('0.4.5.alpha', '0.4.6', True)
    ]

    for current, latest, is_expected in test_cases:
        with CliRunner().isolated_filesystem():
            is_avail = _is_update_avail(
                request_mocker, capsys, current, latest)
            assert is_avail == is_expected, "expected %s compared to %s to yield update availability of %s" % (
                current, latest, is_expected)


def _is_update_avail(request_mocker, capsys, current, latest):
    "Set up the run manager and detect if the upgrade message is printed."
    api = internal.Api(
        load_settings=False,
        retry_timedelta=datetime.timedelta(0, 0, 50))
    api.set_current_run_id(123)
    run = Run()
    run_manager = wandb.run_manager.RunManager(api, run)

    # Without this mocking, during other tests, the _check_update_available
    # function will throw a "mock not found" error, then silently fail without
    # output (just like it would in a normal network failure).
    response = b'{ "info": { "version": "%s" } }' % bytearray(latest, 'utf-8')
    request_mocker.register_uri('GET', 'https://pypi.org/pypi/wandb/json',
                                content=response, status_code=200)
    run_manager._check_update_available(current)

    captured_out, captured_err = capsys.readouterr()
    print(captured_out, captured_err)
    return "To upgrade, please run:" in captured_err


def test_throttle_file_poller(mocker):
    api = internal.Api(load_settings=False)
    with CliRunner().isolated_filesystem():
        run = Run()
        run_manager = wandb.run_manager.RunManager(api, run)
        run_manager._unblock_file_observer()
        run_manager._file_pusher._push_function = lambda *args: None
        emitter = run_manager.emitter
        assert emitter.timeout == 1
        for i in range(100):
            with open(os.path.join(run.dir, "file_%i.txt" % i), "w") as f:
                f.write(str(i))
        try:
            run_manager.shutdown()
        except wandb.apis.UsageError:
            pass
        assert emitter.timeout == 2
