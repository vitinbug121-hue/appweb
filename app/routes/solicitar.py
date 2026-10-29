from app.routes._tarefas import disparar
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import solicitacao

bp = Blueprint("solicitar", __name__, url_prefix="/solicitar")


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        prazo = request.form.get("prazo", "").strip()
        try:
            offset = max(0, int(request.form.get("offset", "0") or 0))
            limite = min(200, max(1, int(request.form.get("limite", "20") or 20)))
        except ValueError:
            flash("Offset e limite devem ser números inteiros.", "erro")
            return redirect(url_for("dashboard.index", _anchor="log"))
        if not prazo:
            flash("Informe o prazo estimado de entrega.", "erro")
            return redirect(url_for("dashboard.index", _anchor="log"))
        disparar("Solicitar (primeira mensagem)", solicitacao.solicitar_lote, prazo, offset, limite)
        return redirect(url_for("dashboard.index", _anchor="log"))
    return render_template("solicitar/index.html", active_page="solicitar")

