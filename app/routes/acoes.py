from app.routes._tarefas import disparar
from flask import Blueprint, redirect, url_for, flash, session

from app.services import mercadopago
from app.services.controle import ativar_parada, liberar_parada

bp = Blueprint("acoes", __name__, url_prefix="/acoes")


@bp.route("/parar", methods=["POST"])
def parar():
    ativar_parada()
    conta_parada = session.get("conta_ativa")
    if conta_parada:
        from app.services.logger import log_evento
        log_evento(conta_parada, "erro", "PARADA DE EMERGÊNCIA acionada: novas execuções ficam bloqueadas até liberar.")
    flash("PARADA DE EMERGÊNCIA ATIVA. Toda execução para na próxima chamada. Use 'Liberar execuções' para retomar.", "danger")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/liberar", methods=["POST"])
def liberar():
    liberar_parada()
    flash("Execuções liberadas. Você já pode iniciar novas ações.", "success")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/atualizar-pagos", methods=["POST"])
def atualizar_pagos_rota():
    disparar("Atualizar pagos (Mercado Pago)", mercadopago.atualizar_pagos)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/executar/<nome_acao>", methods=["POST"])
def executar(nome_acao):
    flash(f"Ação '{nome_acao}' ainda não conectada ao backend real — isso é só o protótipo visual.", "info")
    return redirect(url_for("dashboard.index"))
