from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.db import obter_config_conta
from app.services import mercadolivre

bp = Blueprint("ml_auth", __name__, url_prefix="/ml")


@bp.route("/autorizar", methods=["GET", "POST"])
def autorizar():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("contas.index"))

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()
        if not client_id or not client_secret:
            flash("Informe o Client ID e o Client Secret do seu aplicativo no Mercado Livre.", "erro")
            return redirect(url_for("ml_auth.autorizar"))

        mercadolivre.salvar_credenciais_ml(conta, client_id, client_secret)
        return redirect(mercadolivre.gerar_url_autorizacao(conta))

    return render_template(
        "ml_auth/index.html",
        active_page="ml_auth",
        redirect_uri=mercadolivre.ML_REDIRECT_URI_FIXA,
        config=obter_config_conta(conta),
    )


@bp.route("/codigo", methods=["POST"])
def codigo():
    """Recebe a URL (ou o código) que o Mercado Livre devolveu depois da autorização."""
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("contas.index"))

    code = mercadolivre.extrair_code(request.form.get("retorno", ""))
    if not code:
        flash("Não encontrei o código. Cole a URL completa que apareceu no navegador depois da autorização.", "erro")
        return redirect(url_for("ml_auth.autorizar"))

    sucesso, detalhe = mercadolivre.trocar_code_por_token(conta, code)
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("ml_auth.autorizar"))
