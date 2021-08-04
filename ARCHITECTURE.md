
[DRAFT]


## Concepts

### Processes/Threads

User Context     | Calls wandb.init()
Internal Process | Most processing of users requests
Handler Thread   | Single thread in the internal process to serialize all requests
Sender Thread    | All network operations happen from this thread
Writer Thread    | Runs in parallel with Sender Thread to write a log of transactions

### Records/Results

[https://github.com/wandb/client/blob/master/wandb/proto/wandb_internal.proto](Protobuf Definitions)

## Sequence diagrams

### wandb.init()

```
                 |               |
 User Context    | Shared Queues |       Internal Process       |    Cloud    |
                 |               |                              |             |
                 | rec_q . res_q | HandlerT . WriterT . SenderT |             |
 wandb.init()
 RunRecord   ----1--->
                 |       .       |          .         .         |             |
                     ----------------->
                 |       .       |          .         .         |             |
                                      handle_run()
                 |       .       |          .         .         |             |
                                      ---------->
                 |       .       |          .         .         |             |
                                      --------------------->
                 |       .       |          .         .         |             |
                                                            ----2---->
                 |       .       |          .         .         |             |
                             <------------------------------
                 |       .       |          .         .         |             |
             <---------------
                 |       .       |          .         .         |             |
 RunStartReq ----3---->
                 |       .       |          .         .         |             |
                      ----------------->
                 |       .       |          .         .         |             |
                                       handle_req_run_start()
                 |       .       |          .         .         |             |
                             <----------
                 |       .       |          .         .         |             |
             <----------------

1. communicate_run()
2. upsertBucket
3. communicate_run_start()
```

### wandb.log()
