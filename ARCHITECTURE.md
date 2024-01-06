## Concepts

### Processes/Threads

Ref | Identifier | File | Description
--- | --- | --- | ---
User Context     | N/A | N/A | Users python script: Calls wandb.init(), run.log()
Internal Process | wandb_internal | [internal.py] | Most processing of users requests
HandlerT | HandlerThread | [handler.py] | Single thread in the internal process to serialize all requests
SenderT  | SenderThread  | [sender.py] | All network operations are initiated from this thread
WriterT  | WriterThread  | [writer.py] | Runs in parallel with Sender Thread to write a log of transactions
FS       | FileStreamApi | [file_stream.py] | Thread to make http post requests

### Important data structures

Ref | Data Structure | File | Description
--- | --- | --- | ---
rec_q | record_q | [backend.py] | Queue to pass records to internal process
res_q | result_q | [backend.py] | Queue to pass results from internal process

### Records/Results

Datatypes are encoded as protocol buffers within the wandb library.

There are a few conventions:
- Record is for data that is persisted
- Result is a "reply" for Record
- Request is for internal communication (not persisted)
- Response is a "reply" for Request

Protobuf | File | Description
--- | --- | ---
RunRecord | [wandb_internal.proto] | All run parameters (entity, project, name, id, config, summary)
RunStartRequest | [wandb_internal.proto] | Message to trigger the start of run tracking (start system metrics, etc)
HistoryRecord | [wandb_internal.proto] | Message to send run.log() json history
DeferRequest  | [wandb_internal.proto] | Message to transition states in thread distributed quiesce FSM

### Important functions

Function | File | Description
--- | --- | ---
wandb.init() | [wandb_init.py] | Spin up internal process, create run in cloud, return Run object
handle_run() | [handler.py] | Process RunRecord, hand off to writer and sender
handle_request_run_start() | [handler.py] | Process RunStartRecord, spin up sys metric logging, cache run properties


## More details

See [Developer Docs](docs/dev/) for more detail about wandb internals.
