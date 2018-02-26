import logging
import os
import sys

from flask import Flask, render_template

from wandb.board.app import blueprints
from wandb.board.config import config
from wandb.board.app.graphql.loader import load

BLUEPRINTS = [blueprints.graphql, blueprints.files, blueprints.static]


__all__ = ['create_app']


def create_app(config_name, base_path=None):
    """Create flask app and return it"""
    load(base_path)
    app = Flask(__name__, static_folder="../ui/build/static",
                template_folder="../ui/build")

    configure_app(app, config_name)
    configure_blueprints(app, BLUEPRINTS)
    configure_logging(app)

    @app.errorhandler(404)
    def lost_index(e):
        print("Handled 404")
        return render_template("index.html")

    return app


def configure_app(app, config_name):
    """Initialize configuration"""
    app.config.from_object(config[config_name])


def configure_blueprints(app, blueprints):
    """Configure blueprints in views"""
    for blueprint in blueprints:
        if isinstance(blueprint, str):
            blueprint = getattr(blueprints, blueprint)
        app.register_blueprint(blueprint)


def configure_logging(app):
    """Configure logging"""
    if app.debug:
        logger = logging.getLogger('werkzeug')
        logger.addHandler(logging.StreamHandler(sys.stdout))
