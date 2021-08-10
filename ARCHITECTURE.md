## Concepts

### Processes/Threads

Ref | Identifier | File | Description
--- | --- | --- | ---
User Context     | N/A | N/A | Users python script: Calls wandb.init(), wandb.log()
Internal Process | wandb_internal | [internal.py] | Most processing of users requests
HandlerT | HandlerThread | [handler.py] | Single thread in the internal process to serialize all requests
SenderT  | SenderThread  | [sender.py] | All network operations are initiated from this thread
WriterT  | WriterThread  | [writer.py] | Runs in parallel with Sender Thread to write a log of transactions

### Important data structures

Ref | Data Structure | File | Description
--- | --- | --- | ---
rec_q | record_q | [backend.py] | Queue to pass records to internal process
res_q | result_q | [backend.py] | Queue to pass results from internal process

### Records/Results

Datatypes are encoded as protocol buffers within the client library.

There are a few conventions:
- Record is for data that is persisted
- Result is a "reply" for Record
- Request is for internal communication (not persisted)
- Response is a "reply" for Request

Protobuf | File | Description
--- | --- | ---
RunRecord | [wandb_internal.proto] | All run parameters (entity, project, name, id, config, summary)
RunStartRequest | [wandb_internal.proto] | Message to trigger the start of run tracking (start system metrics, etc)

### Important functions

Function | File | Description
--- | --- | ---
wandb.init() | [wandb_init.py] | Spin up internal process, create run in cloud, return Run object
handle_run() | [handler.py] | Process RunRecord, hand off to writer and sender
handle_request_run_start() | [handler.py] | Process RunStartRecord, spin up sys metric logging, cache run properties

## Sequence diagrams

### wandb.init()

```text
                  |               |                              |
 User Context     | Shared Queues |       Internal Process       |    Cloud
                  |       .       |          .         .         |
                   [rec_q] [res_q] [HandlerT] [WriterT] [SenderT]
                  |       .       |          .         .         |
 wandb.init()
                  |       .       |          .         .         |
 RunRecord    ---[1]--->
                  |       .       |          .         .         |
                      ----------------->
                  |       .       |          .         .         |
                                       handle_run()
                  |       .       |          .         .         |
                                       ---------->
                  |       .       |          .         .         |
                                       --------------------->
                  |       .       |          .         .         |
                                                             ---[2]--->
                  |       .       |          .         .         |
                              <------------------------------
                  |       .       |          .         .         |
              <---------------
                  |       .       |          .         .         |
 RunStartReq  ---[3]---->
                  |       .       |          .         .         |
                       ----------------->
                  |       .       |          .         .         |
                                       handle_request_run_start()
                  |       .       |          .         .         |
                              <----------
                  |       .       |          .         .         |
              <----------------
```


Ref | Message | File | Description
--- | --- | --- | ---
1   | communicate_run()       | [interface.py] | Send a RunRecord to the internal process
2   | UpsertBucket            | [internal_api.py] | GraphQL Upsert Bucket mutation
3   | communicate_run_start() | [interface.py] | Send start run request

### wandb.log()

TODO

### wandb.finish()

TODO

[backend.py]: https://github.com/wandb/client/blob/master/wandb/sdk/backend/backend.py
[handler.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/handler.py
[writer.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/writer.py
[sender.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/sender.py
[interface.py]: https://github.com/wandb/client/blob/master/wandb/sdk/interface/interface.py
[internal_api.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/internal_api.py
[wandb_init.py]: https://github.com/wandb/client/blob/master/wandb/sdk/wandb_init.py
[internal.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/internal.py
[wandb_internal.proto]: https://github.com/wandb/client/blob/master/wandb/proto/wandb_internal.proto
