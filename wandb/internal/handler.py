# -*- coding: utf-8 -*-
"""Handle Manager."""

from __future__ import print_function

import json
import logging
import numbers
import os

import six
import wandb
from wandb.internal import meta, sample, stats, update
from wandb.internal import tb_watcher
from wandb.lib import proto_util
from wandb.proto import wandb_internal_pb2


logger = logging.getLogger(__name__)


class HandleManager(object):
    def __init__(
        self, settings, record_q, result_q, stopped, sender_q, writer_q, interface,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._sender_q = sender_q
        self._writer_q = writer_q
        self._interface = interface

        self._tb_watcher = None
        self._system_stats = None

        # keep track of config and summary from key/val updates
        # self._consolidated_config = dict()
        self._consolidated_summary = dict()
        self._sampled_history = dict()

    def handle(self, record):
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "handle_" + record_type
        handler = getattr(self, handler_str, None)
        logger.debug("handle: {}".format(record_type))
        assert handler, "unknown handle: {}".format(handler_str)
        handler(record)

    def handle_request(self, record):
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "handle_request_" + request_type
        handler = getattr(self, handler_str, None)
        logger.debug("handle_request: {}".format(request_type))
        assert handler, "unknown handle: {}".format(handler_str)
        handler(record)

    def _dispatch_record(self, record):
        if not self._settings.offline:
            self._sender_q.put(record)
        self._writer_q.put(record)

    def handle_request_defer(self, record):
        defer = record.request.defer
        state = defer.state

        logger.info("handle defer: {}".format(state))
        # only handle flush tb (sender handles the rest)
        if state == defer.FLUSH_TB:
            if self._tb_watcher:
                # shutdown tensorboard workers so we get all metrics flushed
                self._tb_watcher.finish()
                self._tb_watcher = None

        self._dispatch_record(record)

    def handle_request_login(self, record):
        self._dispatch_record(record)

    def handle_run(self, record):
        self._dispatch_record(record)

    def handle_stats(self, record):
        self._dispatch_record(record)

    def handle_config(self, record):
        self._dispatch_record(record)

    def handle_output(self, record):
        self._dispatch_record(record)

    def handle_files(self, record):
        self._dispatch_record(record)

    def handle_artifact(self, record):
        self._dispatch_record(record)

    def _save_summary(self, summary_dict):
        summary = wandb_internal_pb2.SummaryRecord()
        for k, v in six.iteritems(summary_dict):
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(v)
        record = wandb_internal_pb2.Record(summary=summary)
        if not self._settings.offline:
            self._sender_q.put(record)

    def _save_history(self, record):
        for item in record.history.item:
            # TODO(jhr) save nested keys?
            k = item.key
            v = json.loads(item.value_json)
            if isinstance(v, numbers.Real):
                self._sampled_history.setdefault(k, sample.UniformSampleAccumulator())
                self._sampled_history[k].add(v)

    def handle_history(self, record):
        self._dispatch_record(record)
        self._save_history(record)
        history_dict = proto_util.dict_from_proto_list(record.history.item)
        self._consolidated_summary.update(history_dict)
        self._save_summary(self._consolidated_summary)

    def handle_summary(self, record):
        summary = record.summary

        for item in summary.update:
            if len(item.nested_key) > 0:
                # we use either key or nested_key -- not both
                assert item.key == ""
                key = tuple(item.nested_key)
            else:
                # no counter-assertion here, because technically
                # summary[""] is valid
                key = (item.key,)

            target = self._consolidated_summary

            # recurse down the dictionary structure:
            for prop in key[:-1]:
                target = target[prop]

            # use the last element of the key to write the leaf:
            target[key[-1]] = json.loads(item.value_json)

        for item in summary.remove:
            if len(item.nested_key) > 0:
                # we use either key or nested_key -- not both
                assert item.key == ""
                key = tuple(item.nested_key)
            else:
                # no counter-assertion here, because technically
                # summary[""] is valid
                key = (item.key,)

            target = self._consolidated_summary

            # recurse down the dictionary structure:
            for prop in key[:-1]:
                target = target[prop]

            # use the last element of the key to erase the leaf:
            del target[key[-1]]

        self._save_summary(self._consolidated_summary)

    def handle_exit(self, record):
        self._dispatch_record(record)

    def handle_request_check_version(self, record):
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        current_version = wandb.__version__
        message = update.check_available(current_version)
        if message:
            result.response.check_version_response.message = message
        self._result_q.put(result)

    def handle_request_run_start(self, record):
        run_start = record.request.run_start
        assert run_start
        assert run_start.run

        if not self._settings._disable_stats and not self._settings.offline:
            pid = os.getpid()
            self._system_stats = stats.SystemStats(pid=pid, interface=self._interface,)
            self._system_stats.start()

        if not self._settings._disable_meta and not self._settings.offline:
            run_meta = meta.Meta(settings=self._settings, interface=self._interface,)
            run_meta.probe()
            run_meta.write()

        self._tb_watcher = tb_watcher.TBWatcher(
            self._settings, interface=self._interface, run_proto=run_start.run,
        )

        result = wandb_internal_pb2.Result(uuid=record.uuid)
        self._result_q.put(result)

    def handle_request_resume(self, data):
        if self._system_stats is not None:
            logger.info("starting system metrics thread")
            self._system_stats.start()

    def handle_request_pause(self, data):
        if self._system_stats is not None:
            logger.info("stopping system metrics thread")
            self._system_stats.shutdown()

    def handle_request_poll_exit(self, record):
        self._dispatch_record(record)

    def handle_request_status(self, record):
        self._dispatch_record(record)

    def handle_request_get_summary(self, data):
        result = wandb_internal_pb2.Result(uuid=data.uuid)
        for key, value in six.iteritems(self._consolidated_summary):
            item = wandb_internal_pb2.SummaryItem()
            item.key = key
            item.value_json = json.dumps(value)
            result.response.get_summary_response.item.append(item)
        self._result_q.put(result)

    def handle_tbrecord(self, record):
        logger.info("handling tbrecord: %s", record)
        if self._tb_watcher:
            tbrecord = record.tbrecord
            self._tb_watcher.add(tbrecord.log_dir, tbrecord.save)
        self._dispatch_record(record)

    def handle_request_sampled_history(self, data):
        result = wandb_internal_pb2.Result(uuid=data.uuid)
        for key, sampled in six.iteritems(self._sampled_history):
            item = wandb_internal_pb2.SampledHistoryItem()
            item.key = key
            values = sampled.get()
            if all(isinstance(i, numbers.Integral) for i in values):
                item.values_int.extend(values)
            elif all(isinstance(i, numbers.Real) for i in values):
                item.values_float.extend(values)
            result.response.sampled_history_response.item.append(item)
        self._result_q.put(result)

    def handle_request_shutdown(self, record):
        # TODO(jhr): should we drain things and stop new requests from coming in?
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        self._result_q.put(result)
        self._stopped.set()

    def finish(self):
        logger.info("shutting down handler")
        if self._tb_watcher:
            self._tb_watcher.finish()


def _config_dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = dict(desc=None, value=json.loads(item.value_json))
    return d
