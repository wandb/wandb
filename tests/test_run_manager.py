import datetime
import io

import wandb.run_manager
from wandb.apis import internal
from wandb.wandb_run import Run

def test_check_update_available_equal(request_mocker, capsys):
    "No update message on equal messages"
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
        is_avail = _is_update_avail(request_mocker, capsys, current, latest)
        assert is_avail == is_expected, "expected %s compared to %s to yield update availability of %s" % (current, latest, is_expected)

def _is_update_avail(request_mocker, capsys, current, latest):
    api = internal.Api(
        load_settings=False,
        retry_timedelta=datetime.timedelta(0, 0, 50))
    api.set_current_run_id(123)
    run = Run()
    run_manager = wandb.run_manager.RunManager(api, run)

    response = b'{ "info": { "version": "%s" } }' % bytearray(latest, 'utf-8')
    request_mocker.register_uri('GET', 'https://pypi.org/pypi/wandb/json',
        content=response, status_code=200)
    run_manager._check_update_available(current)

    captured_out, captured_err = capsys.readouterr()
    return "To upgrade, please run:" in captured_err
