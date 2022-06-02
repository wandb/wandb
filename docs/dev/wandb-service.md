
# wandb service

The wandb service is still experimental.  It can be enabled with:
```
wandb.require(experiment="service")
```

## Grpc service concepts (obects/threads)

Object | File | Description
--- | --- | ---
`_WandbSetup` | wandb/sdk/wandb_setup.py | Singleton shared by the library
`_Manager` | wandb/sdk/wandb_manager.py | Manage the wandb-service (atexit hooks, make sure spun up, pass messages)
`_Service` | wandb/sdk/service/service.py | Actually spin up and pass messages (impl specific)
`SocketServer` | wandb/sdk/service/server_sock.py | Implementation of the wandb service server
`Backend` | wandb/sdk/backend/backend.py | How the user process talks to a internal process
`ServiceSockInterface` | wandb/sdk/service/service_sock.py | How the wandb manager talks to the SocketServer
`StreamMux` | wandb/sdk/service/streams.py | Create/Remove internal.wandb_internal threads
`InterfaceSock` | wandb/sdk/interface/interface_sock.py | User to internal process interface using sockets

## Call stack for wandb.init()

```
wandb.init()
  wandb_setup._setup()
    wandb_setup._setup_manager()
      wandb_manager._Manager()
        service._Service()
        # if there there is no token then call:
        service._Service.start()
          service._Service._launch_server()
            subprocess.Popen("wandb service")
            _wait_for_ports()
        ServiceSockInterface._svc_connect()
          sock_client.connect()

  wandb_setup.Setup._get_manager()
  wandb_manager._Manager._inform_init()
    iface = _get_service_interface()
    ServiceSockInterface._svc_inform_init()
      sock_client.send(inform_init)
        [ --- Wandb Service Context --- ]
        self._mux.add_stream()
        SockServerInterfaceReaderThread()

  backend.Backend()
  backend.ensure_launched()
    backend.ensure_launched_manager()
      wandb_manager._Manager._get_service()
      Backend.interface = InterfaceSock()
      # setup backend interface to point to socket

  backend.interface.communicate_check_version()
  backend.interface.communicate_run()
  backend.interface.communicate_run_start()
    # Similar for all 3 above
    InterfaceSock._communicate_async()
    MessageSockRouter.send_and_receive()
      sock_client.send_record_communicate()
      MessageSockRouter._read_message()
        sock_client.read_server_response()
```
