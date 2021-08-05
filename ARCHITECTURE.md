
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

<pre>
                 |               |
 User Context    | Shared Queues |       Internal Process       |    Cloud    |
                 |               |                              |             |
                 | rec_q . res_q | HandlerT . WriterT . SenderT |             |
 wandb.init()
 RunRecord   ----[<a href="#s-i-1" title="communicate_run()">1</a>]--->
                 |       .       |          .         .         |             |
                     ----------------->
                 |       .       |          .         .         |             |
                                      handle_run()
                 |       .       |          .         .         |             |
                                      ---------->
                 |       .       |          .         .         |             |
                                      --------------------->
                 |       .       |          .         .         |             |
                                                            ----[<a href="#s-i-2" title="UpsertBucket()">2</a>]---->
                 |       .       |          .         .         |             |
                             <------------------------------
                 |       .       |          .         .         |             |
             <---------------
                 |       .       |          .         .         |             |
 RunStartReq ----[<a href="#s-i-3" title="communicate_run_start()">3</a>]---->
                 |       .       |          .         .         |             |
                      ----------------->
                 |       .       |          .         .         |             |
                                       handle_req_run_start()
                 |       .       |          .         .         |             |
                             <----------
                 |       .       |          .         .         |             |
             <----------------
</pre>

--- | --- | ---
<a name="s-i-1"></a>1 | communicate_run() | Send a RunRecord to the internal process
<a name="s-i-2"></a>2 | UpsertBucket | GraphQL Upsert Bucket mutation
<a name="s-i-3"></a>3 | communicate_run_start() | Send start run request

### wandb.log()
