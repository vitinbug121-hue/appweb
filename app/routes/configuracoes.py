from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import mercadopago

bp = Blueprint("configuracoes", __name__, url_prefix="/configuracoes")


@bp.route("/")
def index():
    conta_id = session.get("conta_ativa_id")
    tokens_mp = mercadopago.listar_tokens_mp(conta_id) if conta_id else []
    tokens_reembolso = mercadopago.listar_tokens_reembolso_admin()

    return render_template(
        "configuracoes/index.html",
        active_page="configuracoes",
        tokens_mp=tokens_mp,
        tokens_reembolso=tokens_reembolso,
    )


@bp.route("/tokens-mp/adicionar", methods=["POST"])
def adicionar_token_mp():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("configuracoes.index"))

    token = request.form.get("token", "")
    if not token.strip():
        flash("Informe um token válido.", "erro")
        return redirect(url_for("configuracoes.index"))

    mercadopago.adicionar_token_mp(conta_id, token)
    flash("Token do Mercado Pago adicionado.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-mp/<int:token_id>/remover", methods=["POST"])
def remover_token_mp(token_id):
    mercadopago.remover_token_mp(token_id)
    flash("Token do Mercado Pago removido.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/adicionar", methods=["POST"])
def adicionar_token_reembolso():
    token = request.form.get("token", "")
    if not token.strip():
        flash("Informe um token válido.", "erro")
        return redirect(url_for("configuracoes.index"))

    mercadopago.adicionar_token_reembolso(token)
    flash("Token de reembolso adicionado (compartilhado entre todas as contas).", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/<int:token_id>/remover", methods=["POST"])
def remover_token_reembolso(token_id):
    mercadopago.remover_token_reembolso(token_id)
    flash("Token de reembolso removido.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/<int:token_id>/toggle", methods=["POST"])
def toggle_token_reembolso(token_id):
    mercadopago.toggle_token_reembolso(token_id)
    flash("Estado do token atualizado.", "success")
    return redirect(url_for("configuracoes.index"))
