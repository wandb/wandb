"""Debug subcommands

Commands:
    wandb debug
    wandb debug service
    wandb debug service SERVICE-ID info
    wandb debug service SERVICE-ID run RUN-ID info
    wandb debug service SERVICE-ID run RUN-ID user PID show stacks
    wandb debug service SERVICE-ID run RUN-ID user PID thread THREAD-ID
    wandb debug service SERVICE-ID run RUN-ID user PID thread THREAD-ID info
    wandb debug service SERVICE-ID run RUN-ID internal show threads
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
    os.environ["WANDB_RUN_ID"] = run_id


@click.group()
@click.pass_context
def dbg_thread_node(ctx):
    pass


def _get_interface():
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
    return sock_interface

@click.command()
@click.pass_context
def dbg_run_stacks(ctx):
    sock_interface = _get_interface()
    sock_interface.publish_debug()
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


@click.command()
@click.pass_context
def dbg_thread_stack(ctx):
    pass


def list_threads():
    sock_interface = _get_interface()
    sock_interface.publish_debug()
    data = sock_interface.communicate_debug_poll("data")
    threads = []
    if data:
        for thread in data.data.threads:
            threads.append(f"{thread.name}")
    return threads


@click.command()
@click.pass_context
def dbg_run_threads(ctx):
    threads = list_threads()
    for thread in threads:
        print(thread)


@click.command(hidden=True)
def complete():
    show = """__='\n================================\nHINT: to use this command type:\neval `wandb debug complete`\n================================\nIgnore the following:\n'; autoload -Uz compinit; compinit; if [ ! -r "~/.wandb-complete.zsh" ]; then; _WANDB_COMPLETE=zsh_source wandb > ~/.wandb-complete.zsh; fi; . ~/.wandb-complete.zsh"""
    print(show)


@click.group()
def dbg_run_internal():
    pass


@click.group()
def dbg_run_internal_show():
    pass


@click.group()
def dbg_run_thread_show():
    pass


class CliServices(click.MultiCommand):
    def list_commands(self, ctx):
        services = list_services()
        return services

    def get_command(self, ctx, name):
        return service_subcommand


class CliRuns(click.MultiCommand):

    # https://www.programcreek.com/python/?code=jd%2Fpifpaf%2Fpifpaf-master%2Fpifpaf%2F__main__.py
    def format_commands(self, ctx, formatter):
        # Same as click.MultiCommand.format_commands except it does not use
        # get_command so we don't have to load commands on listing.
        rows = []
        for subcommand in self.list_commands(ctx):
            rows.append((subcommand, 'Run ' + subcommand))

        if rows:
            with formatter.section('Commands'):
                formatter.write_dl(rows)

    def list_commands(self, ctx):
        runs = list_runs()
        return runs

    def get_command(self, ctx, name):
        run_id = name
        os.environ["WANDB_RUN_ID"] = run_id
        return dbg_run_node


class CliThreads(click.MultiCommand):
    def list_commands(self, ctx):
        threads = list_threads()
        return threads

    def get_command(self, ctx, name):
        # TODO: use context obj
        os.environ["WANDB_THREAD_ID"] = name
        return dbg_thread_node


def install_subcommands(base):
    service_cmd = CliServices(name="service", help="Debug services")
    run_cmd = CliRuns(name="run", help="Debug runs")
    thread_cmd = CliThreads(name="thread", help="Debug threads")
    base.add_command(service_cmd)
    base.add_command(run_cmd)
    base.add_command(complete)
    service_subcommand.add_command(run_cmd)

    dbg_run_node.add_command(dbg_run_internal, name="internal")
    dbg_run_internal.add_command(dbg_run_internal_show, name="show")
    dbg_run_internal.add_command(thread_cmd)
    dbg_run_internal_show.add_command(dbg_run_threads, name="threads")
    dbg_run_internal_show.add_command(dbg_run_stacks, name="stacks")

    dbg_run_thread_show.add_command(dbg_thread_stack, name="stack")

    dbg_thread_node.add_command(dbg_run_thread_show, name="show")


from wandb.sdk.lib import filesystem

def init2(name):
    manager = get_manager()
    if not manager:
        print("ERROR: Must run inside wandb-service shell")
        exit(1)
    from wandb import util
    from wandb import Settings
    from wandb.sdk.wandb_settings import Source
    from wandb import setup
    settings = Settings()
    runid = util.generate_id()
    base_settings = setup()
    settings = base_settings.settings.copy()
    settings._apply_init(dict(id=runid))
    settings._set_run_start_time(source=Source.INIT)

    # self._log_setup(settings)
    filesystem._safe_makedirs(os.path.dirname(settings.log_user))
    filesystem._safe_makedirs(os.path.dirname(settings.log_internal))
    filesystem._safe_makedirs(os.path.dirname(settings.sync_file))
    filesystem._safe_makedirs(settings.files_dir)
    filesystem._safe_makedirs(settings._tmp_code_dir)

    got = manager._inform_init(settings=settings, run_id=runid)


import wandb

def init(name):
    manager = get_manager()
    if not manager:
        print("ERROR: Must run inside wandb-service shell")
        exit(1)
    run = wandb.init()


def find_run():
    runs = list_runs()
    if not runs:
        print("ERROR: no runs found")
        exit(1)
    if len(runs) > 1:
        print("WARNING: multiple runs found, using last")
    runid = runs[-1]
    return runid


def log(key, value, image):
    runid = find_run()
    run = wandb.attach(runid)
    key = key or "key"
    data = None
    if value is not None:
        data = value
        try:
            data = int(data)
        except ValueError:
            pass
    if image is not None:
        data = wandb.Image(image)

    data = data or 0

    run.log({key: data})


def finish():
    runid = find_run()
    run = wandb.attach(runid)
    run.finish()
