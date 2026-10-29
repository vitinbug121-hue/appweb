from app.routes._tarefas import disparar
from flask import Blueprint, render_template, redirect, url_for, flash, session

from app.services import brindes

bp = Blueprint("brindes", __name__, url_prefix="/brindes")


def _conta():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
    return conta


@bp.route("/", methods=["GET"])
def index():
    return render_template("brindes/index.html", active_page="brindes")


@bp.route("/enviar-pendentes", methods=["POST"])
def enviar_pendentes():
    disparar("Enviar brindes pendentes", brindes.enviar_brindes_pendentes)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/encerrar-reclamacoes", methods=["POST"])
def encerrar_reclamacoes():
    disparar("Pedir encerramento de reclamações", brindes.encerrar_reclamacoes)
    return redirect(url_for("dashboard.index", _anchor="log"))

