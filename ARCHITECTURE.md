
[DRAFT]


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
                 |               |
 User Context    | Shared Queues |       Internal Process       |    Cloud    |
                 |       .       |          .         .         |             |
                  [rec_q] [res_q] [HandlerT] [WriterT] [SenderT]
                 |       .       |          .         .         |             |
 wandb.init()
                 |       .       |          .         .         |             |
 RunRecord   ----[1]--->
                 |       .       |          .         .         |             |
                     ----------------->
                 |       .       |          .         .         |             |
                                      handle_run()
                 |       .       |          .         .         |             |
                                      ---------->
                 |       .       |          .         .         |             |
                                      --------------------->
                 |       .       |          .         .         |             |
                                                            ----[2]---->
                 |       .       |          .         .         |             |
                             <------------------------------
                 |       .       |          .         .         |             |
             <---------------
                 |       .       |          .         .         |             |
 RunStartReq ----[3]---->
                 |       .       |          .         .         |             |
                      ----------------->
                 |       .       |          .         .         |             |
                                       handle_req_run_start()
                 |       .       |          .         .         |             |
                             <----------
                 |       .       |          .         .         |             |
             <----------------
```

Ref | Item | Description
--- | --- | ---
rec_q    | record_q                | Queue to pass records to internal process
res_q    | result_q                | Queue to pass results from internal process
HandlerT | HandlerThread           | Thread to read record_q
WriterT  | WriterThread            | Thread to write to transaction log
SenderT  | SenderThread            | Thread to make network requests to cloud
1        | communicate_run()       | Send a RunRecord to the internal process
2        | UpsertBucket            | GraphQL Upsert Bucket mutation
3        | communicate_run_start() | Send start run request

### wandb.log()
