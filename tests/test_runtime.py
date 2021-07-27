# import unittest


# from mock import *
# from datetime import datetime, timedelta
# import time  # so we can override time.time

# mock_time = Mock()
# mock_time.return_value = time.mktime(datetime(2011, 6, 21).timetuple())


# class TestCrawlerChecksDates(unittest.TestCase):
#
#     def test_mock_datetime_now(self):
#         self.assertEqual(datetime(2011, 6, 21), datetime.now())

import time
from unittest.mock import patch

# @patch("time.sleep", return_value=None)
def test_runtime(
    mocker,
    mocked_run,
    mock_server,
    _internal_sender,
    _start_backend,
    _stop_backend,
    parse_ctx,
):
    mocker.patch("time.sleep")
    # interface = internal_sender
    # with mock_time as tm:
    threads = _start_backend()
    # interface.publish_run(mocked_run)
    time.sleep(10)
    # interface.publish_pause()
    # time.sleep(10)
    # interface.publish_resume()
    # time.sleep(10)
    _stop_backend(threads=threads)

    ctx_util = parse_ctx(mock_server.ctx)
    print(ctx_util.config["_wandb"])
    assert ctx_util.config["_wandb"]["rt"] >= 30
