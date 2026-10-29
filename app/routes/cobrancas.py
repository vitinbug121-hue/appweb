from app.routes._tarefas import disparar
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import autorizacao, cobrancas, pendencias

bp = Blueprint("cobrancas", __name__, url_prefix="/cobrancas")


def _conta():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
    return conta


def _lote(form):
    texto = (form.get("lote") or "").strip()
    return int(texto) if texto else None


def _mostrar(resumo, rotulo):
    if "erro" in resumo:
        flash(resumo["erro"], "erro")
    else:
        flash(f"{rotulo}: {resumo.get('enviados', 0)} enviado(s), {resumo.get('falhas', 0)} falha(s).",
              "success" if resumo.get("falhas", 0) == 0 else "erro")


@bp.route("/")
def index():
    conta = session.get("conta_ativa")
    lotes = autorizacao.calcular_lotes(conta) if conta else []
    return render_template("cobrancas/index.html", active_page="cobrancas", lotes=lotes)


@bp.route("/erro-boleto", methods=["POST"])
def erro_boleto():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Erro no boleto", cobrancas.erro_boleto, lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/reenviar-boleto", methods=["POST"])
def reenviar_boleto():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Reenviar boleto", cobrancas.reenviar_boleto,
             atraso=request.form.get("atraso") == "on",
             filtrar_frase=request.form.get("filtrar_frase") == "on",
             lote_numero=lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/reenviar-boleto-dobrado", methods=["POST"])
def reenviar_boleto_dobrado():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Reenviar boleto dobrado", cobrancas.reenviar_boleto_dobrado,
             atraso=request.form.get("atraso") == "on",
             filtrar_frase=request.form.get("filtrar_frase") == "on",
             lote_numero=lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/cobrar-dobrado", methods=["POST"])
def cobrar_dobrado():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Cobrança dobrada", cobrancas.cobrar_dobrado,
             request.form.get("metodo", ""), request.form.get("data_entrega", ""), lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/nao-pagos", methods=["POST"])
def nao_pagos():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Cobrar não pagos", pendencias.cobrar_nao_pagos, lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/nao-autorizados", methods=["POST"])
def nao_autorizados():
    try:
        lote = _lote(request.form)
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Cobrar não autorizados", pendencias.cobrar_nao_autorizados, lote)
    return redirect(url_for("dashboard.index", _anchor="log"))

