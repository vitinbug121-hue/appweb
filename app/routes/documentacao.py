from flask import Blueprint, render_template

bp = Blueprint("documentacao", __name__, url_prefix="/documentacao")


@bp.route("/")
def index():
    return render_template("documentacao/index.html", active_page="documentacao")
