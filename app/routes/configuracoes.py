from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import loja as loja_service

from app.db import (
    adicionar_token_mp,
    adicionar_token_reembolso,
    alternar_token_reembolso,
    listar_tokens_mp,
    listar_tokens_reembolso,
    remover_token_mp,
    remover_token_reembolso,
)

bp = Blueprint("configuracoes", __name__, url_prefix="/configuracoes")


@bp.route("/")
def index():
    conta = session.get("conta_ativa")
    return render_template(
        "configuracoes/index.html",
        active_page="configuracoes",
        loja=loja_service.obter_loja(conta),
        tokens_mp=listar_tokens_mp(conta) if conta else [],
        tokens_reembolso=listar_tokens_reembolso(),
    )


@bp.route("/loja/salvar", methods=["POST"])
def salvar_loja_rota():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("configuracoes.index"))

    ok, mensagem = loja_service.salvar_loja(conta, request.form)
    flash(mensagem, "success" if ok else "erro")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-mp/adicionar", methods=["POST"])
def adicionar_token_mp_rota():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("configuracoes.index"))

    token = request.form.get("token", "")
    if not token.strip():
        flash("Informe um token válido.", "erro")
        return redirect(url_for("configuracoes.index"))

    adicionar_token_mp(conta, token)
    flash("Token do Mercado Pago adicionado.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-mp/<string:token_id>/remover", methods=["POST"])
def remover_token_mp_rota(token_id):
    remover_token_mp(token_id)
    flash("Token do Mercado Pago removido.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/adicionar", methods=["POST"])
def adicionar_token_reembolso_rota():
    token = request.form.get("token", "")
    if not token.strip():
        flash("Informe um token válido.", "erro")
        return redirect(url_for("configuracoes.index"))

    adicionar_token_reembolso(token)
    flash("Token de reembolso adicionado (compartilhado entre todas as contas).", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/<string:token_id>/remover", methods=["POST"])
def remover_token_reembolso_rota(token_id):
    remover_token_reembolso(token_id)
    flash("Token de reembolso removido.", "success")
    return redirect(url_for("configuracoes.index"))


@bp.route("/tokens-reembolso/<string:token_id>/toggle", methods=["POST"])
def toggle_token_reembolso_rota(token_id):
    alternar_token_reembolso(token_id)
    flash("Estado do token atualizado.", "success")
    return redirect(url_for("configuracoes.index"))
