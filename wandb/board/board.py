import os
from flask import url_for
from wandb.board.app import create_app
from wandb.board.app.graphql.schema import Run, Project
from wandb.board.app.models import Dir
from wandb.board.app.graphql.loader import data, find_run

app = create_app(os.getenv('FLASK_CONFIG') or 'default')  # TODO: configure env


@app.cli.command()
def list_routes():
    output = []
    from six.moves import urllib
    for rule in app.url_map.iter_rules():

        options = {}
        for arg in rule.arguments:
            options[arg] = "[{0}]".format(arg)

        methods = ','.join(rule.methods)
        url = url_for(rule.endpoint, **options)
        line = urllib.parse.unquote("{:50s} {:20s} {}".format(
            rule.endpoint, methods, url))
        output.append(line)

    for line in sorted(output):
        print(line)


@app.shell_context_processor
def make_shell_context():
    return dict(Run=Run, Project=Project, Dir=Dir, data=data, find_run=find_run)


if __name__ == "__main__":
    app.run("0.0.0.0", 7177, threaded=True)
