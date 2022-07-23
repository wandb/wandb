## Sequence diagrams

### wandb.init()

```text
                  |               |                                   |
 User Context     | Shared Queues |          Internal Process         |  Cloud
                  |       .       |          .         .         .    |
                   [rec_q] [res_q] [HandlerT] [WriterT] [SenderT] [FS]
                  |       .       |          .         .         .    |
 wandb.init()
                  |       .       |          .         .         .    |
 RunRecord     --[1]-->
                  |       .       |          .         .         .    |
                      ----------------->
                  |       .       |          .         .         .    |
                                       handle_run()
                  |       .       |          .         .         .    |
                                       _dispatch_record()
                  |       .       |          .         .         .    |
                                       ---------->
                  |       .       |          .         .         .    |
                                       -------------------->
                  |       .       |          .         .         .    |
                                                           send_run()
                  |       .       |          .         .         .    |
                                                           ----------[2]--->
                  |       .       |          .         .         .    |
                              <-----------------------------
                  |       .       |          .         .         .    |
              <----------------
                  |       .       |          .         .         .    |
 RunStartReq   --[3]-->
                  |       .       |          .         .         .    |
                       ---------------->
                  |       .       |          .         .         .    |
                                       handle_request_run_start()
                  |       .       |          .         .         .    |
                              <---------
                  |       .       |          .         .         .    |
              <----------------
                  |       .       |          .         .         .    |
 run._on_start()
                  |       .       |          .         .         .    |
 run._display_run()
                  |       .       |          .         .         .    |
 RunStatusChecker()
                  |       .       |          .         .         .    |
 run._console_start()
                  |       .       |          .         .         .    |
```

Ref | Message | File | Description
--- | --- | --- | ---
1   | communicate_run()       | [interface.py] | Send a RunRecord to the internal process
2   | UpsertBucket            | [internal_api.py] | GraphQL Upsert Bucket mutation
3   | communicate_run_start() | [interface.py] | Send start run request

### run.log()

```text
                  |               |                                   |
 User Context     | Shared Queues |          Internal Process         |  Cloud
                  |       .       |          .         .         .    |
                   [rec_q] [res_q] [HandlerT] [WriterT] [SenderT] [FS]
                  |       .       |          .         .         .    |
 run.log()
                  |       .       |          .         .         .    |
 run.history._row_add()
                  |       .       |          .         .         .    |
 run._history_callback()
                  |       .       |          .         .         .    |
 publish_history()
                  |       .       |          .         .         .    |
 history_dict_to_json()
                  |       .       |          .         .         .    |
 HistoryRecord --[1]-->
                  |       .       |          .         .         .    |
                      ----------------->
                  |       .       |          .         .         .    |
                                       handle_history()
                  |       .       |          .         .         .    |
                                       _history_update()
                  |       .       |          .         .         .    |
                                       _history_assign_step()
                  |       .       |          .         .         .    |
                                       _dispatch_record()
                  |       .       |          .         .         .    |
                                       ---------->
                  |       .       |          .         .         .    |
                                       -------------------->
                  |       .       |          .         .         .    |
                                                           send_history()
                  |       .       |          .         .         .    |
                                                           _fs.push()
                  |       .       |          .         .         .    |
                                                           -------->
                  |       .       |          .         .         .    |
                                                                   --[2]-->
                  |       .       |          .         .         .    |
                                       _update_summary()
                  |       .       |          .         .         .    |
```

Ref | Message | File | Description
--- | --- | --- | ---
1   | \_publish\_history()    | [interface.py] | Send a HistoryRecord to the internal process
2   | client.post()           | [file_stream.py] | Http post json to cloud server

### run.finish()

```text
                  |               |                                   |
 User Context     | Shared Queues |          Internal Process         |  Cloud
                  |       .       |          .         .         .    |
                   [rec_q] [res_q] [HandlerT] [WriterT] [SenderT] [FS]
                  |       .       |          .         .         .    |
 run.finish()
                  |       .       |          .         .         .    |
 run._atexit_cleanup()
                  |       .       |          .         .         .    |
 run._on_finish()
                  |       .       |          .         .         .    |
 RunStatusChecker.stop()
                  |       .       |          .         .         .    |
 run._console_stop()
                  |       .       |          .         .         .    |
 TelemRecord   --[1]-->
                  |       .       |          .         .         .    |
                      ---------------> _dispatch_record() ...
                  |       .       |          .         .         .    |
 RunExitRecord --[2]-->
                  |       .       |          .         .         .    |
                      --------------->
                  |       .       |          .         .         .    |
                                       handle_exit()
                  |       .       |          .         .         .    |
                                       _dispatch_record() ...
                  |       .       |          .         .         .    |
                                       ---------->
                  |       .       |          .         .         .    |
                                       -------------------->
                  |       .       |          .         .         .    |
                                                           send_exit()
                  |       .       |          .         .         .    |
                      <----------[3]------------------------
                  |       .       |          .         .         .    |
 PollExitReq   --[4]-->
                  |       .       |          .         .         .    |
                      --------------->
                  |       .       |          .         .         .    |
                                       handle_request_poll_exit()
                  |       .       |          .         .         .    |
                                       _dispatch_record()
                  |       .       |          .         .         .    |
                                       -------------------->
                  |       .       |          .         .         .    |
                                                           send_req_poll_exit()
                  |       .       |          .         .         .    |
                              <-----------------------------
                  |       .       |          .         .         .    |
              <----------------
                  |       .       |          .         .         .    |
                      --------------->
                  |       .       |          .         .         .    |
                                       handle_request_defer()
                  |       .       |          .         .         .    |
                                       _dispatch_record()
                  |       .       |          .         .         .    |
                                       -------------------->
                  |       .       |          .         .         .    |
                                                           send_request_defer()
                  |       .       |          .         .         .    |
                                                           (until FSM done)
                  |       .       |          .         .         .    |
                      <----------[3]------------------------
                  |       .       |          .         .         .    |
 _on_finish_progress()
                  |       .       |          .         .         .    |
 PollExitReq   --[4]--> (See PollExitReq transactions above)
                  |       .       |          .         .         .    |
              <----------------
                  |       .       |          .         .         .    |
 GetSummaryReq --[5]-->
                  |       .       |          .         .         .    |
 SampledHisReq --[6]-->
                  |       .       |          .         .         .    |
 run._on_final()
                  |       .       |          .         .         .    |
 run._show_*()
                  |       .       |          .         .         .    |
```

Ref | Message | File | Description
--- | --- | --- | ---
1   | publish_telemetry() | [interface.py] | Send final telemetry information
2   | publish_exit() | [interface.py] | Send exit code from the script
3   | publish_defer() | [interface.py] | Start or transition to next state in FSM
4   | communicate_poll_exit() | [interface.py] | Poll if the internal process has quiesced queues
5   | communicate_summary() | [interface.py] | Get current summary cached in the handler
6   | communicate_sampled_history() | [interface.py] | Get sampled history cached in the handler

TODO: Document Defer Finite State Machine

[backend.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/backend/backend.py
[handler.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/handler.py
[writer.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/writer.py
[sender.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/sender.py
[interface.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/interface/interface.py
[internal_api.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/internal_api.py
[wandb_init.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/wandb_init.py
[internal.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/internal.py
[file_stream.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/internal/file_stream.py
[wandb_internal.proto]: https://github.com/wandb/wandb/blob/master/wandb/proto/wandb_internal.proto
