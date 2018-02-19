from flask import Blueprint, render_template

static = Blueprint('static', __name__)


@static.route("/")
def index():
    return render_template("index.html")


@static.errorhandler(404)
def lost_index(e):
    return render_template("index.html")
