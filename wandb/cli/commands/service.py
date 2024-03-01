from typing import Optional

import click

from wandb.cli.utils.errors import display_error


@click.command(
    name="service",
    context_settings={"default_map": {}},
    help="Run a wandb service",
    hidden=True,
)
@click.option(
    "--sock-port", default=None, type=int, help="The host port to bind socket service."
)
@click.option("--port-filename", default=None, help="Save allocated port to file.")
@click.option("--address", default=None, help="The address to bind service.")
@click.option("--pid", default=None, type=int, help="The parent process id to monitor.")
@click.option("--debug", is_flag=True, default=False, help="log debug info")
@click.option("--serve-sock", is_flag=True, default=False, help="use socket mode")
@display_error
def service(
    sock_port: Optional[int],
    port_filename: Optional[str],
    address: Optional[str],
    pid: Optional[int],
    debug: bool,
    serve_sock: bool,
):
    from wandb.sdk.service.server import WandbServer

    server = WandbServer(
        sock_port=sock_port,
        port_fname=port_filename,
        address=address,
        pid=pid,
        debug=debug,
        serve_sock=serve_sock,
    )
    server.serve()
