import click
import psutil

def list_services():
    TOKEN = "wandb-service("
    TOKEN_END = ")"
    for proc in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        cmdline = proc.info.get("cmdline", [])
        prog = next(iter(cmdline or []), "")
        if prog.startswith(TOKEN) and prog.endswith(TOKEN_END):
            svc_token = prog[len(TOKEN):-len(TOKEN_END)]
            print("proc:", svc_token)
            # 2-47261-s-63976
            ver, pid, typ, port = svc_token.split("-")
            assert int(ver) == 2

def list_runs():
    pass

@click.command()
def service():
    print("service")
    list_services()


@click.command()
def run():
    print("run")


@click.command()
def junk():
    print("junk")

class CliRuns(click.MultiCommand):

    def list_commands(self, ctx):
        return ["r1", "r2", "r3"]

    def get_command(self, ctx, name):
        return junk


def install_subcommands(base):
    base.add_command(service)
    run = CliRuns(name="run", help='This tool\'s subcommands are loaded from a '
            'plugin folder dynamically.')
    base.add_command(run)
