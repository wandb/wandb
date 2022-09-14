import threading
import time
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

from wandb.proto import wandb_internal_pb2 as pb

# from wandb.sdk.interface.interface_shared import InterfaceShared
from wandb.sdk.lib.mailbox import Mailbox, MailboxProbe, MailboxProgress


def get_test_setup():
    mailbox = Mailbox()
    handle = mailbox.get_handle()
    run_result = pb.RunUpdateResult()
    run_result.run.run_id = "this_is_me"
    result = pb.Result(run_result=run_result)
    return mailbox, handle, result


def test_normal():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_me"


def test_deliver_wrong_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = "bad_mail_slot"
    mailbox.deliver(result)
    got_result = handle.wait(timeout=1)
    assert got_result is None


def test_deliver_released_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_me"

    # mail slot has been released, lets redeliver to nowhere
    result2 = pb.Result()
    result2.CopyFrom(result)
    result2.run_result.run.run_id = "this_is_new"
    mailbox.deliver(result2)

    # our handler should timeout
    got_result = handle.wait(timeout=1)
    assert got_result is None


def test_redeliver_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1, release=False)
    assert got_result.run_result.run.run_id == "this_is_me"

    # mail slot has been released, lets redeliver to nowhere
    result2 = pb.Result()
    result2.CopyFrom(result)
    result2.run_result.run.run_id = "this_is_new"
    mailbox.deliver(result2)

    # our handler should see the old data
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_new"


class TestWithMockedTime(TestCase):
    def setUp(self):
        self._orig_event_class = threading.Event
        self._time_elapsed = 0

    def _advance_time(self, time_increment):
        self._time_elapsed += time_increment
        time.sleep(time_increment)

    @property
    def elapsed_time(self):
        return self._time_elapsed

    def _mocked_event(selftest, **kwargs):  # noqa: N805
        class _TestEvent(selftest._orig_event_class):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

            def wait(self, **kwargs):
                result = super().wait(timeout=0)
                if result:
                    return result
                # advance time
                timeout = kwargs.get("timeout")
                if timeout is not None:
                    selftest._advance_time(timeout)
                return result

        event = _TestEvent(**kwargs)
        return event

    @contextmanager
    def _patch_mailbox(self):
        def _setup_time(time_mock):
            now = time.time()
            time_mock.side_effect = [now + i for i in range(30)]

        def _wait(self_wait, timeout):
            wait_result = self_wait._event.wait(timeout=0)
            if wait_result:
                return wait_result
            self._advance_time(timeout)
            return wait_result

        with patch(
            "wandb.sdk.lib.mailbox._MailboxSlot._wait", new=_wait
        ) as event_mock, patch(
            "wandb.sdk.lib.mailbox.MailboxHandle._time"
        ) as time_mock:

            _setup_time(time_mock)
            yield (event_mock, time_mock)

    def test_on_probe(self):
        def on_probe(probe_handle):
            pass

        with self._patch_mailbox() as (event_mock, time_mock):
            mailbox, handle, result = get_test_setup()
            mock_on_probe = Mock(spec=on_probe)
            handle.add_probe(mock_on_probe)
            _ = handle.wait(timeout=3)
            assert mock_on_probe.call_count == 2
            assert len(mock_on_probe.call_args.args) == 1
            assert isinstance(mock_on_probe.call_args.args[0], MailboxProbe)
            assert self.elapsed_time >= 3

    def test_on_progress(self):
        def on_progress(progress_handle):
            pass

        with self._patch_mailbox() as (event_mock, time_mock):
            mailbox, handle, result = get_test_setup()
            mock_on_progress = Mock(spec=on_progress)
            handle.add_progress(mock_on_progress)
            _ = handle.wait(timeout=3)
            assert mock_on_progress.call_count == 2
            assert len(mock_on_progress.call_args.args) == 1
            assert isinstance(mock_on_progress.call_args.args[0], MailboxProgress)

    def test_keepalive(self):
        with self._patch_mailbox() as (event_mock, time_mock):
            mailbox = Mailbox()
            mailbox.enable_keepalive()

            record = pb.Record()
            iface = Mock(
                spec_set=[
                    "publish",
                    "_publish",
                    "transport_failed",
                    "_transport_mark_failed",
                    "_transport_mark_success",
                    "_transport_keepalive_failed",
                ]
            )
            iface.transport_failed = Mock(return_value=False)
            iface._transport_keepalive_failed = Mock(return_value=False)

            handle = mailbox._deliver_record(record, iface)
            _ = handle.wait(timeout=2)
            assert iface._transport_keepalive_failed.call_count == 2
