from app.routes._tarefas import disparar
from flask import Blueprint, render_template, redirect, url_for, flash, session

from app.db import listar_vendas_reembolsaveis, obter_tokens_reembolso
from app.services import mercadopago

bp = Blueprint("reembolso", __name__, url_prefix="/reembolso")


@bp.route("/")
def index():
    conta = session.get("conta_ativa")
    vendas = listar_vendas_reembolsaveis(conta) if conta else []
    tokens_cadastrados = len(obter_tokens_reembolso())
    return render_template(
        "reembolso/index.html",
        active_page="reembolso",
        vendas=vendas,
        tokens_cadastrados=tokens_cadastrados,
    )


@bp.route("/<string:order_id>/reembolsar", methods=["POST"])
def reembolsar(order_id):
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("dashboard.index", _anchor="log"))

    sucesso, detalhe = mercadopago.reembolsar_venda(conta, order_id)
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/reembolsar-todos", methods=["POST"])
def reembolsar_todos():
    disparar("Reembolso em lote", mercadopago.reembolsar_todos)
    return redirect(url_for("dashboard.index", _anchor="log"))

