import os
from .app import create_app
from .app.graphql.schema import Run, Project
from .app.models import Dir
from .app.graphql.loader import data, find_run

app = create_app(os.getenv('FLASK_CONFIG') or 'default')  # TODO: configure env


@app.shell_context_processor
def make_shell_context():
    return dict(Run=Run, Project=Project, Dir=Dir, data=data, find_run=find_run)


if __name__ == "__main__":
    app.run("0.0.0.0", 7177, threaded=True)
