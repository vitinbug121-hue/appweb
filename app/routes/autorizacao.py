from app.routes._tarefas import disparar
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import autorizacao

bp = Blueprint("autorizacao", __name__, url_prefix="/autorizacao")


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            limite = int(request.form.get("limite", "20") or 20)
            lote = request.form.get("lote", "").strip() or None
            lote = int(lote) if lote else None
        except ValueError:
            flash("Quantidade e lote devem ser números inteiros.", "erro")
            return redirect(url_for("dashboard.index", _anchor="log"))
        disparar("Taxar e autorizar", autorizacao.autorizar_lote,
                 request.form.get("forma", ""), request.form.get("data_entrega", ""), lote, limite)
        return redirect(url_for("dashboard.index", _anchor="log"))
    lotes = autorizacao.calcular_lotes(session.get("conta_ativa")) if session.get("conta_ativa") else []
    return render_template("autorizacao/index.html", active_page="autorizacao", lotes=lotes)

