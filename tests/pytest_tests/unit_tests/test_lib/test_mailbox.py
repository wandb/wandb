import sys
import threading
import time
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

from parameterized import parameterized
from wandb.proto import wandb_internal_pb2 as pb
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


class TimeObject:
    def __init__(self):
        self._time_elapsed = 0
        self._time_start = 0
        now = time.monotonic()
        self._time_start = now
        self._timed_events = []

    def add_time_mock(self, time_mock):
        time_mock.side_effect = self.get_time

    @property
    def elapsed_time(self):
        return self._time_elapsed

    def advance_time(self, time_increment):
        self._time_elapsed += time_increment
        self._run_timed_events()

    def _run_timed_events(self):
        reschedule = []
        for time_offset, callback in self._timed_events:
            if time_offset > self._time_elapsed:
                reschedule.append((time_offset, callback))
                continue
            callback()
        self._timed_events = reschedule

    def add_timed_event(self, time_offset, callback):
        if time_offset < 0:
            return
        self._timed_events.append((time_offset, callback))
        self._run_timed_events()

    def get_time(self):
        now = self._time_start + self._time_elapsed
        return now


class TestWithMockedTime(TestCase):
    def setUp(self):
        self._orig_event_class = threading.Event
        self._time_obj = TimeObject()

    @property
    def time_obj(self):
        return self._time_obj

    @contextmanager
    def _patch_mailbox(self):
        def _wait(self_wait, timeout):
            wait_result = self_wait._event.wait(timeout=0)
            if wait_result:
                return wait_result
            self.time_obj.advance_time(timeout)
            return wait_result

        with patch("wandb.sdk.lib.mailbox.MailboxHandle._time") as time_mock, patch(
            "wandb.sdk.lib.mailbox.Mailbox._time"
        ) as time_all_mock, patch(
            "wandb.sdk.lib.mailbox._MailboxSlot._wait", new=_wait
        ) as event_mock, patch(
            "wandb.sdk.lib.mailbox._MailboxWaitAll._wait", new=_wait
        ) as event_all_mock:
            self.time_obj.add_time_mock(time_mock)
            self.time_obj.add_time_mock(time_all_mock)
            yield (event_mock, event_all_mock)

    def test_on_probe(self):
        def on_probe(probe_handle):
            pass

        with self._patch_mailbox() as (event_mock, _):
            mailbox, handle, result = get_test_setup()
            mock_on_probe = Mock(spec=on_probe)
            handle.add_probe(mock_on_probe)
            _ = handle.wait(timeout=3)
            self.assertEqual(mock_on_probe.call_count, 2)
            if sys.version_info[:2] >= (3, 8):  # call_args.args only in 3.8+
                self.assertIsInstance(mock_on_probe.call_args.args[0], MailboxProbe)
            self.assertTrue(self.time_obj.elapsed_time >= 3)

    def test_on_progress(self):
        def on_progress(progress_handle):
            pass

        with self._patch_mailbox() as (event_mock, _):
            mailbox, handle, result = get_test_setup()
            mock_on_progress = Mock(spec=on_progress)
            handle.add_progress(mock_on_progress)
            _ = handle.wait(timeout=3)
            self.assertEqual(mock_on_progress.call_count, 2)
            if sys.version_info[:2] >= (3, 8):  # call_args.args only in 3.8+
                self.assertIsInstance(
                    mock_on_progress.call_args.args[0], MailboxProgress
                )

    def test_keepalive(self):
        """Make sure mock keepalive is called."""
        with self._patch_mailbox() as (event_mock, _):
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
            self.assertEqual(iface._transport_keepalive_failed.call_count, 2)

    def test_wait_stop(self):
        def on_progress(progress_handle):
            progress_handle.wait_stop()

        with self._patch_mailbox() as (event_mock, _):
            mailbox, handle, result = get_test_setup()
            mock_on_progress = Mock(spec=on_progress, side_effect=on_progress)
            handle.add_progress(mock_on_progress)

            result.control.mailbox_slot = handle.address
            self.time_obj.add_timed_event(2, lambda: mailbox.deliver(result))

            result = handle.wait(timeout=3)
            self.assertEqual(result, None)
            self.assertEqual(mock_on_progress.call_count, 1)
            if sys.version_info[:2] >= (3, 8):  # call_args.args only in 3.8+
                self.assertIsInstance(
                    mock_on_progress.call_args.args[0], MailboxProgress
                )

    @parameterized.expand(
        [
            # deliver1_offset, deliver2_offset, expected, elapsed
            (-1, -1, False, 8),
            (1, -1, False, 8),
            (-1, 1, False, 8),
            (2, 4, True, 4),
        ]
    )
    def test_wait_all(self, deliver1_offset, deliver2_offset, expected, elapsed):
        def on_progress_all(progress_all_handle):
            pass

        with self._patch_mailbox() as (
            event_mock,
            event_all_mock,
        ):
            mailbox = Mailbox()
            handle1 = mailbox.get_handle()
            handle2 = mailbox.get_handle()

            result1 = pb.Result()
            result1.control.mailbox_slot = handle1.address
            self.time_obj.add_timed_event(
                deliver1_offset, lambda: mailbox.deliver(result1)
            )

            result2 = pb.Result()
            result2.control.mailbox_slot = handle2.address
            self.time_obj.add_timed_event(
                deliver2_offset, lambda: mailbox.deliver(result2)
            )

            got = mailbox.wait_all(
                [handle1, handle2], on_progress_all=on_progress_all, timeout=8
            )
            self.assertEqual(got, expected)
            self.assertEqual(self.time_obj.elapsed_time, elapsed)
