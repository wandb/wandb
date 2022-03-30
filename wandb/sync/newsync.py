import asyncio
import multiprocessing as mp
import pathlib
import tempfile
from typing import List

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore
from wandb.util import check_and_warn_old


WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"
TMPDIR = tempfile.TemporaryDirectory()


class Manager:
    def __init__(self, live: bool = False):
        # self._config = None
        # self._server = None
        # self._manager = None
        # self._pid = pid
        self.live = live
        self.sync_items: List[pathlib.Path] = []

        print("Hello from Manager")

    def _robust_scan(self, ds):
        """Attempt to scan data, handling incomplete files"""
        try:
            return ds.scan_data()
        except AssertionError as e:
            if ds.in_last_block() and not self.live:
                wandb.termwarn(
                    f".wandb file is incomplete ({e}), "
                    "be sure to sync this run again once it's finished or run"
                )
                return None
            else:
                raise e

    def _parse_pb(self, data, exit_pb=None):
        pb = wandb_internal_pb2.Record()
        pb.ParseFromString(data)
        record_type = pb.WhichOneof("record_type")
        # print("Record:", pb)
        # print("Record type:", record_type)
        # if self._view:
        #     if self._verbose:
        #         print("Record:", pb)
        #     else:
        #         print("Record:", record_type)
        #     return pb, exit_pb, True
        if record_type == "run":
            # if self._run_id:
            #     pb.run.run_id = self._run_id
            # if self._project:
            #     pb.run.project = self._project
            # if self._entity:
            #     pb.run.entity = self._entity
            pb.control.req_resp = True
        elif record_type == "exit":
            exit_pb = pb
            return pb, exit_pb, True
        elif record_type == "final":
            assert exit_pb, "final seen without exit"
            pb = exit_pb
            exit_pb = None
        return pb, exit_pb, False

    def _parse_protobuf(self, data):
        protobuf = wandb_internal_pb2.Record()
        protobuf.ParseFromString(data)
        record_type = protobuf.WhichOneof("record_type")

        # what is your talent, Pedro? Magic!

        # return record_type, protobuf
        return None

    def run(self):
        asyncio.run(self._run())

    async def _run(self):
        sync_tasks = []
        for sync_item in self.sync_items:
            print("Creating sync task for", sync_item)
            sync_tasks.append(
                asyncio.create_task(self._process_item(sync_item))
            )
        await asyncio.gather(*sync_tasks)

    async def _process_item(self, sync_item: pathlib.Path):
        if sync_item.is_dir():
            files = list(map(str, sync_item.glob("**/*")))
            filtered_files = list(filter(lambda f: f.endswith(WANDB_SUFFIX), files))
            if check_and_warn_old(files) or len(filtered_files) != 1:
                print(f"Skipping directory: {sync_item}")
                return None
            if len(filtered_files) > 0:
                sync_item = sync_item / filtered_files[0]

        root_dir = sync_item.parent
        # sm = sender.SendManager.setup(root_dir)

        ds = datastore.DataStore()
        try:
            ds.open_for_scan(sync_item)
        except AssertionError as e:
            print(f".wandb file is empty ({e}), skipping: {sync_item}")
            return None

        # use multiprocessing pool map to parse protobufs
        # process pool to handle protobuf parsing
        pool = mp.Pool(processes=mp.cpu_count())
        # pool = mp.Pool(processes=1)
        data = []
        while True:
            batch = self._robust_scan(ds)
            if batch is None:
                break
            data.append(batch)
            # self._parse_protobuf(batch)
        results = pool.map(self._parse_protobuf, data)
        # print([r[0] for r in results])
        pool.close()
        pool.join()

        # # save exit for final send
        # exit_pb = None
        # finished = False
        # shown = False
        # while True:
        #     data = self._robust_scan(ds)
        #     # print("Data:", data)
        #     # input()
        #     if data is None:
        #         break
        #     pb, exit_pb, cont = self._parse_pb(data, exit_pb)
        #     if exit_pb is not None:
        #         finished = True
        #     if cont:
        #         continue
        #     # sm.send(pb)
        #     # # send any records that were added in previous send
        #     # while not sm._record_q.empty():
        #     #     data = sm._record_q.get(block=True)
        #     #     sm.send(data)
        #     #
        #     # if pb.control.req_resp:
        #     #     result = sm._result_q.get(block=True)
        #     #     result_type = result.WhichOneof("result_type")
        #     #     if not shown and result_type == "run_result":
        #     #         r = result.run_result.run
        #     #         # TODO(jhr): hardcode until we have settings in sync
        #     #         url = "{}/{}/{}/runs/{}".format(
        #     #             self._app_url,
        #     #             url_quote(r.entity),
        #     #             url_quote(r.project),
        #     #             url_quote(r.run_id),
        #     #         )
        #     #         print("Syncing: %s ..." % url, end="")
        #     #         sys.stdout.flush()
        #     #         shown = True
        # # sm.finish()
        # # Only mark synced if the run actually finished
        # # if self._mark_synced and not self._view and finished:
        # #     synced_file = "{}{}".format(sync_item, SYNCED_SUFFIX)
        # #     with open(synced_file, "w"):
        # #         pass
        # print("done.")
