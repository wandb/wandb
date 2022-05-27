import os
import click
import psutil

from wandb.sdk import wandb_manager

def list_services():
    TOKEN = "wandb-service("
    TOKEN_END = ")"
    ret = []
    for proc in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        cmdline = proc.info.get("cmdline", [])
        prog = next(iter(cmdline or []), "")
        if prog.startswith(TOKEN) and prog.endswith(TOKEN_END):
            svc_token = prog[len(TOKEN):-len(TOKEN_END)]
            # 2-47261-s-63976
            ver, pid, typ, port = svc_token.split("-")
            assert int(ver) == 2
            parts = (ver, pid, "tcp", "localhost", port)
            svc = "-".join(parts)
            ret.append(svc)
    return ret


def get_manager(service=None):
    if not service:
        services = list_services()
        if not services:
            # no service, no runs
            return None
        # assume just one, handle later
        assert len(services) == 1
        service = services[0]
    os.environ["WANDB_SERVICE"] = service
    settings = dict()
    manager = wandb_manager._Manager(settings)
    manager._inform_connect()
    return manager

def list_runs(service=None):
    manager = get_manager()
    if not manager:
        return []
    got = manager._inform_list()
    return got


@click.command()
def service():
    print("service")
    services = list_services()


@click.command()
def run():
    pass


@click.command()
@click.pass_context
def run_subcommand(ctx):
    # print("junk", vars(ctx))
    run_id = ctx.info_name
    manager = get_manager()
    if not manager:
        return

    svc = manager._get_service()
    assert svc
    svc_iface = svc.service_interface

    svc_transport = svc_iface.get_transport()

    assert svc_transport == "tcp"
    from wandb.sdk.interface.interface_sock import InterfaceSock

    # svc_iface_sock = cast("ServiceSockInterface", svc_iface)
    svc_iface_sock = svc_iface
    sock_client = svc_iface_sock._get_sock_client()
    sock_interface = InterfaceSock(sock_client)
    sock_interface._stream_id = run_id
    sock_interface.publish_debug("junk")
    data = sock_interface.communicate_debug_poll("data")
    data_list = data.traceback.split("\n")
    for l in data_list:
        print(l)



class CliRuns(click.MultiCommand):

    def list_commands(self, ctx):
        runs = list_runs()
        return runs

    def get_command(self, ctx, name):
        return run_subcommand


def install_subcommands(base):
    base.add_command(service)
    run = CliRuns(name="run", help='This tool\'s subcommands are loaded from a '
            'plugin folder dynamically.')
    base.add_command(run)
