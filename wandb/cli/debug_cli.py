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


def list_runs(service=None):

    if not service:
        services = list_services()
        if not services:
            # no service, no runs
            return []
        # assume just one, handle later
        assert len(services) == 1
        service = services[0]

    os.environ["WANDB_SERVICE"] = service
    settings = dict()
    manager = wandb_manager._Manager(settings)

    manager._inform_connect()

    got = manager._inform_list()
    return got


@click.command()
def service():
    print("service")
    services = list_services()


@click.command()
def run():
    print("run")


@click.command()
def junk():
    print("junk")

class CliRuns(click.MultiCommand):

    def list_commands(self, ctx):
        runs = list_runs()
        # return ["r1", "r2", "r3"]
        return runs

    def get_command(self, ctx, name):
        return junk


def install_subcommands(base):
    base.add_command(service)
    run = CliRuns(name="run", help='This tool\'s subcommands are loaded from a '
            'plugin folder dynamically.')
    base.add_command(run)
