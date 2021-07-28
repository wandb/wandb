
[DRAFT]

Life of a Run
```
                                                             |                               |
User Context                                                 |         Shared Queues         |       Internal Process
                                                             |                               |
wandb.init()                                                                                  
     |                                                       |                               |
    wandb.sdk.wandb_init.init()                               
     |                                                       |                               |
    wandb.sdk.wandb_init._WandbInit                           
     |                                                       |                               |
    wandb.sdk.wandb_init._WandbInit.setup()                   
     |                                                       |                               |
    wandb.sdk.wandb_setup._setup()                            
     |                                                       |                               |
    wandb.sdk.backend.backend.Backend                         
     |                                                       |                               |
    wandb.sdk.backend.backend.Backend.ensure_lauched()  ----------  record_q    result_q  --------   wandb.sdk.internal.internal.wandb_internal
     |                                                       |                               |
     |                                                                                               HandlerThread    WriterThread    SenderThread
     |                                                       |                               |
    wandb.sdk.wandb_run.Run                                                                                    
     |                                                       |                               |
    return Run


wandb.log()

```
