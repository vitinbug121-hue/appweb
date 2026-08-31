from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.db import get_connection
from app.services import mercadolivre

bp = Blueprint("ml_auth", __name__, url_prefix="/ml")


def _redirect_uri_atual():
    # request.url_root já vem com barra no final (ex: "http://127.0.0.1:5000/")
    return request.url_root.rstrip("/") + url_for("ml_auth.callback")


@bp.route("/autorizar", methods=["GET", "POST"])
def autorizar():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("contas.index"))

    redirect_uri = _redirect_uri_atual()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()

        if not client_id or not client_secret:
            flash("Informe o Client ID e o Client Secret do seu aplicativo no Mercado Livre.", "erro")
            return redirect(url_for("ml_auth.autorizar"))

        mercadolivre.salvar_credenciais_ml(conta_id, client_id, client_secret, redirect_uri)

        url_autorizacao = mercadolivre.gerar_url_autorizacao(conta_id, redirect_uri)
        # Manda o navegador do usuário direto pra tela de autorização do ML —
        # equivalente ao webbrowser.open() do sistema desktop, só que sem
        # precisar depois copiar/colar o código manualmente: o ML já vai
        # redirecionar de volta pro nosso /ml/callback sozinho.
        return redirect(url_autorizacao)

    conn = get_connection()
    config = conn.execute(
        "SELECT ml_client_id, ml_seller_id FROM config_conta WHERE conta_id = ?", (conta_id,)
    ).fetchone()
    conn.close()

    return render_template(
        "ml_auth/index.html",
        active_page="ml_auth",
        redirect_uri=redirect_uri,
        config=config,
    )


@bp.route("/callback")
def callback():
    conta_id = session.get("conta_ativa_id")
    code = request.args.get("code")

    if not conta_id:
        flash("Sessão perdida — selecione a conta novamente e tente autorizar de novo.", "erro")
        return redirect(url_for("contas.index"))

    if not code:
        erro = request.args.get("error_description") or request.args.get("error") or "código de autorização não recebido."
        flash(f"Autorização cancelada ou falhou: {erro}", "erro")
        return redirect(url_for("ml_auth.autorizar"))

    redirect_uri = _redirect_uri_atual()
    sucesso, detalhe = mercadolivre.trocar_code_por_token(conta_id, code, redirect_uri)

    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("ml_auth.autorizar"))
