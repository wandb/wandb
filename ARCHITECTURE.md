
## Concepts

### Processes/Threads

Context | Description
--- | ---
User Context     | Calls wandb.init()
Internal Process | Most processing of users requests
Handler Thread   | Single thread in the internal process to serialize all requests
Sender Thread    | All network operations happen from this thread
Writer Thread    | Runs in parallel with Sender Thread to write a log of transactions

### Records/Results

Datatypes are encoded as protocol buffers within the client library.

There are a few conventions:
- Record is for data that is persisted
- Result is a "reply" for Record
- Request is for internal communication (not persisted)
- Response is a "reply" for Request

[Protobuf definition](https://github.com/wandb/client/blob/master/wandb/proto/wandb_internal.proto)

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

Ref | Data Structure | File | Description
rec_q | record_q | [backend.py] | Queue to pass records to internal process
res_q | result_q | [backend.py] | Queue to pass results from internal process

Ref | Thread | File | Description
HandlerT | HandlerThread | [handler.py] | Thread to read record_q
WriterT  | WriterThread  | [writer.py] | Thread to write to transaction log
SenderT  | SenderThread  | [sender.py] | Thread to make network requests to cloud

Ref | Message | File | Description
--- | --- | --- | ---
1   | communicate_run()       | [interface.py] | Send a RunRecord to the internal process
2   | UpsertBucket            | [internal_api.py] | GraphQL Upsert Bucket mutation
3   | communicate_run_start() | [interface.py] | Send start run request

Function | File | Description
--- | --- | ---
wandb.init() | [wandb_init.py] | Spin up internal process, create run in cloud, return Run object
handle_run() | [handler.py] | Process RunRecord, hand off to writer and sender
handle_request_run_start() | [handler.py] | Process RunStartRecord, spin up sys metric logging, cache run properties

[backend.py]: https://github.com/wandb/client/blob/master/wandb/sdk/backend/backend.py
[handler.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/handler.py
[writer.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/writer.py
[sender.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/sender.py
[interface.py]: https://github.com/wandb/client/blob/master/wandb/sdk/interface/interface.py
[internal_api.py]: https://github.com/wandb/client/blob/master/wandb/sdk/internal/internal_api.py
[wandb_init.py]: https://github.com/wandb/client/blob/master/wandb/sdk/wandb_init.py

### wandb.log()

### wandb.finish()
