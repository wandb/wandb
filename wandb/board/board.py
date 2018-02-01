import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

from app import create_app
from app.graphql.schema import Run, Project
from app.models import Dir
from app.graphql.loader import data, find_run

app = create_app(os.getenv('FLASK_CONFIG') or 'default')  # TODO: configure env


@app.shell_context_processor
def make_shell_context():
    return dict(Run=Run, Project=Project, Dir=Dir, data=data, find_run=find_run)
