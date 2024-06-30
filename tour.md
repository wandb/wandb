# A Guided Tour of the SDK repo

Don’t panic! Inspect sequence diagrams and
click through code references in your IDE instead.

Let us explore what happens when the user casts
the magical spell “with just a few lines of code…”:

```python
import wandb

run = wandb.init()
run.log({"loss": 0.01})
run.finish()  # (or not)
```

## What happens when you call `wandb.init()`?

```python
import wandb

run = wandb.init()
```

The `wandb.init()` function is an alias for `wandb.sdk.wandb_init.init()`.
We'll use the full name here to make it clear what's happening.

```python
wandb.init == wandb.sdk.wandb_init.init
# so we really called
run = wandb.sdk.wandb_init.init()
```

We first create a `wandb.sdk.wandb_init._WandbInit` object and call
its `setup` method with the arguments passed to `wandb.init()`.

```python
wi = wandb.sdk.wandb_init._WandbInit()
wi.setup(kwargs)
```

The most important thing that happens in `setup` is that we create a
singleton object `wandb.sdk.wandb_init._WandbSetup`:

```python
wi._wl = wandb.sdk.wandb_setup.setup(settings=setup_settings)
```

This creates an instance of `wandb.sdk.wandb_setup._WandbSetup__WandbSetup` class
and assigns it to `wi._wl._instance` -- a (per-process) singleton object that
handles setting up and tearing down the W&B library context,
including settings, logging, backend communication, and more.
("wl" stands for "wandb library").

In the process, we then call `wandb.sdk.wandb_setup._WandbSetup__WandbSetup._setup()`
to set up the W&B library context. In particular, we set up the Manager
(an instance of `wandb.sdk.wandb_manager._Manager`) and assign it to
`wi._wl._instance._manager`.

The Manager manages connecting to and communicating with the W&B service process.
It handles setup/teardown, getting a connection token, interfacing with the service,
informing the service of lifecycle events, and more.

Manager sets up Service:

```python
wi._wl._instance._manager._service = wandb.sdk.service._Service()
```

If `wandb-service` is not already running, we start it up and connect to it:

```python
wi._wl._instance._manager._service.start()
wi._wl._instance._manager._service_connect()
```

Notably, `_service.start()` calls `_service._launch_server()` that is actually
spinning up the `wandb-service` process:

```python
wi._wl._instance._manager._service.internal_proc = subprocess.Popen(
    [
        python_executable,  # properly discovered python executable
        "-m",
        "wandb",
        "service",
        "--port-filename",
        fname,
        "--pid",
        pid,
        "--debug",
        "--serve-sock",
    ],
    ...,
)
```

---

We are now in the `wandb-service` land, dear reader!

What happens then? `python -m wandb service ...` triggers the `wandb.cli.cli.service`
function that is defined in `wandb/cli/cli.py`. It sets up a
`wandb.sdk.service.server.WandbServer` object and calls its `serve` method.

```python
server = WandbServer(...)
server.serve()
```

That in turn does the service side of the wandb SDK magic. It creates a
`StreamMux` object (multiplexer) that manages internal threads for each run.
It also creates a socket server (`wandb.sdk.service.server_sock.SocketServer` instance)
that the user process can connect to, which uses the multiplexer to manage
the threads.

```python
mux = StreamMux()
sock_port = self._start_sock(mux=mux)

# which calls:
address: str = self._address or "127.0.0.1"
port: int = self._sock_port or 0
self._sock_server = SocketServer(mux=mux, address=address, port=port)
self._sock_server.start()

# `start()` in turn does:
self._thread = SockAcceptThread(sock=self._sock, mux=self._mux)
self._thread.start()
```

This spins up a thread (`SockAcceptThread`) that listens for incoming connections
on the socket and creates a new thread (`SockServerReadThread`) for each connection.
That new thread then handles the communication with the user process.
The multiplexer is used to manage the threads.

Back in `serve()`, we then start the multiplexer's action-listening loop:
```python
mux.loop()
```

For example, when the socket server receives an `inform_init` request from
the user process (as we will later see) in the corresponding (to the connection)
`SockServerReadThread` thread, it will trigger the `server_inform_init` method
using python's dynamic method invocation (`getattr`):

```python
# self = SockServerReadThread
sreq = self._sock_client.read_server_request()
sreq_type = sreq.WhichOneof("server_request_type")
shandler_str = "server_" + sreq_type
shandler: "Callable[[spb.ServerRequest], None]" = getattr(self, shandler_str, None)
shandler(sreq)
```

(This is why if you try to find all the places where `server_inform_init` is called
using your IDE or by grep'ping, you won't find any. It's called dynamically.
Similar logic is applied to e.g. the handler methods -- see below.)

The `server_inform_init` method then calls the `_mux.add_stream` method, which
creates an "add" action and puts it on the multiplexer's queue. `StreamMux`'s loop
then picks it up from the queue and cals `_process_add` creating a new thread
(`StreamThread`) that will handle the communication with the user process.

It is that `StreamThread` that spins up the legendary
`wandb.sdk.internal.internal.wandb_internal` function:

```python
def wandb_internal(
    settings: "SettingsDict",
    record_q: "Queue[Record]",
    result_q: "Queue[Result]",
    port: Optional[int] = None,
    user_pid: Optional[int] = None,
) -> None:
    """Internal process function entrypoint.

    Read from record queue and dispatch work to various threads.

    Arguments:
        settings: dictionary of configuration parameters.
        record_q: records to be handled
        result_q: for sending results back

    """
    # mark this process as internal
    wandb._set_internal_process()
    ...
```

Notably, it spins up the Sender, the Writer, and the Handler threads:

```python
record_sender_thread = SenderThread(...)
record_writer_thread = WriterThread(...)
record_handler_thread = HandlerThread(...)
```

When initializing the internal process, we will pass the corresponding stream's
queues to these threads (connecting everything together, so to speak),
so that they can communicate with the user process.

[TODO: expand]
Once `wandb.init()` is complete, the user process will be producing messages/records
and sending them over the socket connection to the internal process, where they
would eventually be handled by the `HandlerThread` thread, (potentially) written to
the append-only levelDB database (the `.wandb` file) by the `WriterThread` thread,
and sent to the W&B backend by the `SenderThread` thread.

[TODO:] Flow control in the internal process: what happens when the network connection
is funky?

---

Back in the user process, `_manager._service_connect()` gets the Service interface
and connects to it:

```python
svc_iface = self._get_service_interface()
# an instance of ` wandb.sdk.service.service_sock.ServiceSockInterface`
# stored at wi._wl._instance._manager._service.service_interface
svc_iface._svc_connect(port=port)
# which calls `ServiceSockInterface._sock_client.connect(port=port)`
```

At this point we are finally done with the setup and can start using the `wi` object.
Back in `wandb_init.py`, we call its `init` method to create a Run object:

```python
run = wi.init()
```

It asks the the Manager to send a `ServerInformInitRequest` notifying the
`wandb-service` that we are starting a run:

```python
manager._inform_init(settings=self.settings, run_id=self.settings.run_id)
```

You already know what happens next: the `SockServerReadThread` thread on the
wandb-service side picks up the request and calls the `server_inform_init` method,
which in turn calls `_mux.add_stream` and creates a new `StreamThread` thread,
which in turn spins up the `wandb.sdk.internal.internal.wandb_internal` function,
which in turn spins up the Sender, the Writer, and the Handler threads. Huzzah!

The `init()` then function sets up a `wandb.backend.backend.Backend` object that
is essentially a convenience wrapper around a few goodies available through
the Manager object (and more). In part it is used as an adapter to the Manager object.
Note: When the user disbles `wandb-service`, it is the Backend that spins things up
the old way (see `ensure_launched()`; i.e. spins up the "internal process" with
either python's `multithreading` or `multiprocessing`).

We then create a `wandb.sdk.wandb_run.Run` object and set it up, in particular:

```python
run._set_library(wi._wl)
run._set_backend(backend)
```

We communicate with the Service process via our socket connection and
ask it to create the run for us:

```python
run_init_handle = backend.interface.deliver_run(run)
result = run_init_handle.wait(
    timeout=timeout,
    on_progress=self._on_progress_init,
    cancel=True,
)
if result:
    run_result = result.run_result

run._set_run_obj(run_result.run)
```

`deliver_run` creates a Protobuf message of type `RunRecord`
out of the partially set-up Run object and sends it to the Service process
that in turn communicates with the W&B backend (Gorilla!) to create a run for us.

Here, you can see how nice it is to have the Mailbox abstraction: `deliver_run`
return a handle that we can wait on to get the result of the operation.

```python
manager._inform_start(settings=self.settings, run_id=self.settings.run_id)

run_start_handle = backend.interface.deliver_run_start(run._run_obj)
run_start_result = run_start_handle.wait(timeout=30)

wi._wl._global_run_stack.append(run)
wi.run = run

run._on_start()
```

The `run_start` request will eventually make its way to the handler thread
in the Service process where we will set up things like the run start time
and the System Monitor (`wandb.sdk.internal.system.system_monitor.SystemMonitor`)
that we use to collect system metrics.

`_on_start()` sets up the `wandb.run = run` and other global, library-level variables,
prints the header everyone knows and loves, saves code, starts the `RunStatusChecker`
(that periodically checks if the user has requested a stop, the network status, and
the run sync status), and initiates console logging.

We are now ready to start logging metrics, artifacts, etc.!
