from app.routes._tarefas import disparar
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import asaas, asaas_selenium, autorizacao, pix

bp = Blueprint("pix", __name__, url_prefix="/pix")


@bp.route("/", methods=["GET"])
def index():
    conta = session.get("conta_ativa")
    lotes = autorizacao.calcular_lotes(conta) if conta else []
    return render_template("pix/index.html", active_page="pix", lotes=lotes)


@bp.route("/atualizar-pagos", methods=["POST"])
def atualizar_pagos():
    disparar("Atualizar PIX pagos", pix.atualizar_pix_pagos)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/aviso-boleto", methods=["POST"])
def aviso_boleto():
    try:
        lote = request.form.get("lote", "").strip() or None
        lote = int(lote) if lote else None
    except ValueError:
        flash("Lote inválido.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))
    disparar("Aviso PIX → boleto", pix.aviso_pix_para_boleto, lote)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/asaas-atualizar", methods=["POST"])
def asaas_atualizar():
    disparar("Atualizar Asaas (API)", asaas.atualizar_asaas_pagos)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/asaas-navegador", methods=["POST"])
def asaas_navegador():
    disparar("Atualizar Asaas (navegador)", asaas_selenium.atualizar_asaas_navegador)
    return redirect(url_for("dashboard.index", _anchor="log"))



@bp.route("/marcar-manual", methods=["POST"])
def marcar_manual():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("pix.index"))
    r = pix.marcar_pagos_manual(conta, request.form.get("ordens", ""), request.form.get("tipo", "taxa"))
    if "erro" in r:
        flash(r["erro"], "erro")
        return redirect(url_for("pix.index"))
    partes = [f"{len(r['marcadas'])} marcada(s) como paga(s)"]
    if r["ignoradas"]:
        detalhes = "; ".join(f"{oid}: {motivo}" for oid, motivo in r["ignoradas"][:10])
        partes.append(f"{len(r['ignoradas'])} ignorada(s) ({detalhes}{'...' if len(r['ignoradas']) > 10 else ''})")
    flash("Baixa manual: " + " · ".join(partes), "success" if not r["ignoradas"] else "erro")
    return redirect(url_for("pix.index"))
