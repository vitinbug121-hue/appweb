from flask import Blueprint, redirect, url_for, flash, session

from app.services import mercadopago

bp = Blueprint("acoes", __name__, url_prefix="/acoes")


@bp.route("/parar", methods=["POST"])
def parar():
    # No projeto final: seta um Event/flag compartilhado que os
    # services em background verificam para interromper o processamento.
    flash("Stop urgente acionado! O processamento será interrompido assim que possível.", "danger")
    return redirect(url_for("dashboard.index"))


@bp.route("/atualizar-pagos", methods=["POST"])
def atualizar_pagos_rota():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("dashboard.index"))

    resumo = mercadopago.atualizar_pagos(conta_id)
    flash(
        f"Atualização concluída — verificados: {resumo['verificados']}, "
        f"pagos agora: {resumo['pagos']}, vencidos: {resumo['vencidos']}, erros: {resumo['erros']}.",
        "success" if resumo["erros"] == 0 else "erro",
    )
    return redirect(url_for("dashboard.index"))


@bp.route("/executar/<nome_acao>", methods=["POST"])
def executar(nome_acao):
    # Placeholder: no projeto final, aqui entra a chamada ao service
    # correspondente, rodando em background e emitindo logs via SSE.
    flash(f"Ação '{nome_acao}' ainda não conectada ao backend real — isso é só o protótipo visual.", "info")
    return redirect(url_for("dashboard.index"))
