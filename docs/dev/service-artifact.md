
# service artifact

This file describes what happens with the following snippet (after wandb.init()):

```python
wandb.require(experiment="service")
# ...
run = wandb.init()
artifact = wandb.Artifact("my-dataset", type="dataset")
art = run.log_artifact(artifact)
art.wait()
```

## Sequence diagram

```mermaid
sequenceDiagram
  participant user_context
  participant grpc
  participant shared_queues
  participant internal_threads
  participant cloud

  Note over user_context: run.log_artifact()
  Note over user_context: communicate_artifact() [1]
  Note over user_context: LogArtifactRequest
  Note over user_context: _communicate_artifact()[2]
  Note over user_context: ArtifactSendRequest
  
  user_context ->> grpc: [3]
  grpc ->> shared_queues: [4]
  shared_queues ->> internal_threads: 
  
  Note over internal_threads: handle_request_artifact_send()
  Note over internal_threads: send_request_artifact_send()
  
  internal_threads ->> shared_queues: 
  shared_queues ->> grpc: 
  grpc ->> user_context: 
  
  Note over user_context: MessageFuturePoll()
  Note over user_context: art.wait()
  Note over user_context: ArtifactPollRequest
  
  user_context ->> grpc: [5]
  grpc ->> shared_queues: [6]
  shared_queues ->> internal_threads: 
  
  Note over internal_threads: handle_request_artifact_poll()
  
  internal_threads ->> shared_queues: 
  shared_queues ->> grpc: 
  grpc ->> user_context: 
  internal_threads ->> shared_queues: [7]
  
  shared_queues ->> internal_threads: 
  Note over internal_threads: handle_request_artifact_done()
  

  user_context ->> grpc: [5]
  grpc ->> shared_queues: [6]
  shared_queues ->> internal_threads: 
  
  Note over internal_threads: handle_request_artifact_poll()
  
  internal_threads ->> shared_queues: 
  shared_queues ->> grpc: 
  grpc ->> user_context: 

```

Ref | Message/Function | File | Description
--- | --- | --- | ---
1   | `communicate_artifact()`       | [interface.py]   | Online form of log_artifact
2   | `_communicate_artifact()`      | [iface_grpc.py]  | Emulate log_artifact with polling wait
3   | Grpc: ArtifactSend             | [grpc_server.py] | gRPC send artifact to server
4   | `_communicate_artifact_send()` | [interface.py]   | handle GRPC and pass to internal threads
5   | Grpc: ArtifactPoll             | [grpc_server.py] | gRPC poll artifact status
6   | `_communicate_artifact_poll()` | [interface.py]   | handle GRPC and pass polling to handler
7   | `_publish_artifact_done()`     | [interface.py]   | artifact send is done (error or success)

[interface.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/interface/interface.py
[iface_grpc.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/interface/iface_grpc.py
[grpc_server.py]: https://github.com/wandb/wandb/blob/master/wandb/sdk/service/grpc_server.py
