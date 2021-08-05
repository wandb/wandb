
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

``                 |               |``
`` User Context    | Shared Queues |       Internal Process       |    Cloud    |``
``                 |               |                              |             |``
                 | rec_q . res_q | HandlerT . WriterT . SenderT |             |
 wandb.init()
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

[1]: #seq-init-communicate-run
[2]: #seq-init-upsert-bucket
[3]: #seq-init-communicate-run-start
``

Message | Description
--- | ---
<a name="seq-init-communicate-run"></a>communicate_run() | Send a RunRecord to the internal process
<a name="seq-init-upsert-bucket"></a>UpsertBucket | GraphQL Upsert Bucket mutation
<a name="seq-init-communicate-run-start"></a>communicate_run_start() | Send start run request

### wandb.log()
