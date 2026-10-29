from app.routes._tarefas import disparar
from flask import Blueprint, flash, redirect, render_template, session, url_for

from app.services import encerradas

bp = Blueprint("encerradas", __name__, url_prefix="/encerradas")


@bp.route("/", methods=["GET"])
def index():
    return render_template("encerradas/index.html", active_page="encerradas")


@bp.route("/atualizar", methods=["POST"])
def atualizar():
    disparar("Atualizar vendas encerradas", encerradas.atualizar_vendas_encerradas)
    return redirect(url_for("dashboard.index", _anchor="log"))

