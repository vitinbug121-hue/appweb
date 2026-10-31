from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.routes._tarefas import disparar
from app.services import mensagem_manual

bp = Blueprint("mensagem", __name__, url_prefix="/mensagem")


@bp.route("/", methods=["GET"])
def index():
    return render_template("mensagem/index.html", active_page="mensagem")


@bp.route("/enviar", methods=["POST"])
def enviar():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("mensagem.index"))

    texto = request.form.get("texto", "")
    if not mensagem_manual.normalizar_texto(texto):
        flash("Escreva a mensagem antes de enviar.", "erro")
        return redirect(url_for("mensagem.index"))
    if request.form.get("confirmo") != "on":
        flash("Confirme que o texto deve ser enviado aos compradores listados.", "erro")
        return redirect(url_for("mensagem.index"))

    disparar("Mensagem personalizada", mensagem_manual.enviar, texto, request.form.get("ordens", ""))
    return redirect(url_for("dashboard.index", _anchor="log"))
