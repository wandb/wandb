
# Internal docs

## Grpc Server Architecture

                  |                                   |
    UserMain      |              GrpcServer           |
                  |                                   |

                  |       Mux       ~   Internal*N    |
                    [mgr_i] [mgr_o]   [rec_q] [rsp_q] 
                  |        .        ~                 |
 wandb.setup()      
                  |        .        ~                 |
 StartProcess  --[1]-->
                  |        .        ~                 |
              <--[2]-----------
                  |        .        ~                 |
 EnsureUp      --[3]-->
                  |        .        ~                 |
              <--[4]-----------
                  |        .        ~                 |
 wandb.init()
                  |        .        ~                 |
 UserInitMsg   --[5]-->
                  |        .        ~                 |
              <--[6]-----------
                  |        .        ~                 |
 ...
                  |        .        ~                 |
 wandb.log()
                  |        .        ~                 |
               --[7]-->
                  |        .        ~                 |
              <--[8]-----------
                  |        .        ~                 |
 wandb.finish()
                  |        .        ~                 |
 UserFinMsg    --[9]-->
                  |        .        ~                 |
              <--[a]-----------
                  |        .        ~                 |
 ...
                  |        .        ~                 |
 atexit
                  |        .        ~                 |
 ManagerStop   --[b]-->
                  |        .        ~                 |
              <--[c]-----------
                  |        .        ~                 |
 ManagerPoll   --[d]-->
                  |        .        ~                 |
              <--[e]-----------
                  |        .        ~                 |
