# wandb service

The wandb service is still experimental. It can be enabled with:

```
wandb.require(experiment="service")
```

## Installation

`service` is currently installed as an extra:

```bash
pip install --upgrade wandb[service]
```

If you are using Pytorch-Lightning please also install this costum branch:

```bash
pip install --force git+https://github.com/wandb/pytorch-lightning.git@wandb-service-attach
```

(This branch will be upstreamed and be part of the regular Pytorch Lightning package.)

## Grpc Server Architecture

(TODO: This diagram is out of date)

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

## Files to modify:

| File                                                                                                   | Description         |
| ------------------------------------------------------------------------------------------------------ | ------------------- |
| [grpc_server.py](https://github.com/wandb/client/blob/master/wandb/sdk/service/grpc_server.p)          | Stars a GRPC server |
| [interface_grpc.py](https://github.com/wandb/client/blob/master/wandb/sdk/interface/interface_grpc.py) | TODO                |
| [router.py](https://github.com/wandb/client/blob/master/wandb/sdk/interface/router.py)                 | TODO                |
| [service.py](https://github.com/wandb/client/blob/master/wandb/sdk/service/service.py)                 | TODO                |
| [wandb_manager.py](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_manager.py)             | TODO                |
| [backend.py](https://github.com/wandb/client/blob/master/wandb/sdk/backend/backend.py)                 | TODO                |

## FAQs

### If your scrip is stuck in a restart loop

Please try adding:

```python
if __name__ == "__main__":
    <your-script-goes-here>
```

### AssertionError: start method 'fork' is not supported yet

If the start method is not `fork` and you are running in a new enviroment try re-running your script to resolve this error message.
