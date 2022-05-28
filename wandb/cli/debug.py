"""Debug subcommands

Commands:
    wandb debug
    wandb debug service
    wandb debug service SERVICE-ID info
    wandb debug service SERVICE-ID run RUN-ID info
    wandb debug service SERVICE-ID run RUN-ID user PID info
    wandb debug service SERVICE-ID run RUN-ID user PID show stacks
    wandb debug service SERVICE-ID run RUN-ID user PID thread THREAD-ID
    wandb debug service SERVICE-ID run RUN-ID user PID thread THREAD-ID info
    wandb debug service SERVICE-ID run RUN-ID internal info
    wandb debug service SERVICE-ID run RUN-ID internal show stacks
    wandb debug service SERVICE-ID run RUN-ID internal thread THREAD-ID show stack

"""

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
    service = service or os.environ.get("WANDB_SERVICE")
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


# @click.command()
@click.group(help="Debug service")
@click.pass_context
def service_subcommand(ctx):
    service_id = ctx.info_name
    os.environ["WANDB_SERVICE"] = service_id


@click.group(help="Debug run")
def dbg_run():
    pass


@click.group()
@click.pass_context
def dbg_run_node(ctx):
    run_id = ctx.info_name
    # print("GOT RUN", run_id)
    os.environ["WANDB_RUN_ID"] = run_id


@click.command()
@click.pass_context
def dbg_run_stacks(ctx):
    # print("junk", vars(ctx))
    run_id = os.environ["WANDB_RUN_ID"]
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
    # print("GOT", data)
    if not data:
        return
    for thread in data.data.threads:
        print(f"{thread.name}")
        for frame in thread.stack:
            print(f"\t{frame.filename} {frame.lineno}")
            print(f"\t\t{frame.line}")
            for var in frame.locals:
                print(f"\t\t\t{var.var}")
                print(f"\t\t\t\t{var.type}")
                print(f"\t\t\t\t{var.repr}")
    # data_list = data.traceback.split("\n")
    # for l in data_list:
    #     print(l)


@click.group()
def dbg_run_internal():
    pass


@click.group()
def dbg_run_internal_show():
    pass


class CliServices(click.MultiCommand):
    def list_commands(self, ctx):
        services = list_services()
        return services

    def get_command(self, ctx, name):
        return service_subcommand


class CliRuns(click.MultiCommand):
    def list_commands(self, ctx):
        runs = list_runs()
        return runs

    def get_command(self, ctx, name):
        return dbg_run_node


def install_subcommands(base):
    service_cmd = CliServices(name="service", help="Debug services")
    run_cmd = CliRuns(name="run", help="Debug runs")
    base.add_command(service_cmd)
    base.add_command(run_cmd)
    service_subcommand.add_command(run_cmd)

    dbg_run_node.add_command(dbg_run_internal, name="internal")
    dbg_run_internal.add_command(dbg_run_internal_show, name="show")
    dbg_run_internal_show.add_command(dbg_run_stacks, name="stacks")
