# wandb service

## Grpc Server Architecture

(TODO: This diagram is out of date)

```text
                  |                                   |
    UserMain      |              GrpcServer           |
                  |                                   |

                  |       Mux       ~   Internal*N    |
                    [mgr_i] [mgr_o]   [rec_q] [rsp_q]
                  |        .        ~                 |

wandb.setup()
| . ~ |
StartProcess --[1]-->
| . ~ |
<--[2]-----------
| . ~ |
EnsureUp --[3]-->
| . ~ |
<--[4]-----------
| . ~ |
wandb.init()
| . ~ |
UserInitMsg --[5]-->
| . ~ |
<--[6]-----------
| . ~ |
...
| . ~ |
wandb.log()
| . ~ |
--[7]-->
| . ~ |
<--[8]-----------
| . ~ |
wandb.finish()
| . ~ |
UserFinMsg --[9]-->
| . ~ |
<--[a]-----------
| . ~ |
...
| . ~ |
atexit
| . ~ |
ManagerStop --[b]-->
| . ~ |
<--[c]-----------
| . ~ |
ManagerPoll --[d]-->
| . ~ |
<--[e]-----------
| . ~ |
```

## Relevant files:

| File                                                                                                   | Description                                                                                                     |
| ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| [grpc_server.py](https://github.com/wandb/client/blob/master/wandb/sdk/service/grpc_server.p)          | Contains the gRPC server (`GrpcServer`), wandb servicer (`WandbServicer`) and the streaming logic (`StreamMux`) |
| [service.py](https://github.com/wandb/client/blob/master/wandb/sdk/service/service.py)                 | Contains the logic to launch the gRPC server as a background process and connect to client processes            |
| [wandb_manager.py](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_manager.py)             | The Manger is responsible for                                                                                   |
| [interface_grpc.py](https://github.com/wandb/client/blob/master/wandb/sdk/interface/interface_grpc.py) | Interface between the client process (`stub`) and the gRPC service                                              |
| [backend.py](https://github.com/wandb/client/blob/master/wandb/sdk/backend/backend.py)                 | Responsible for launching the manager                                                                           |
| [interface.py](https://github.com/wandb/client/blob/master/wandb/sdk/interface/interface.py)           |                                                                                                                 |
| [router.py](https://github.com/wandb/client/blob/master/wandb/sdk/interface/router.py)                 |                                                                                                                 |
