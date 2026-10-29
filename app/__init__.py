import os

from flask import Flask, session

# Carrega o .env antes de qualquer leitura de variável. Este módulo roda
# na importação de qualquer parte do pacote (inclusive app.worker).
from app.env import carregar_env

carregar_env()

from app.db import init_indices, listar_contas


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "")
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY não configurada no arquivo .env")

    # Índices do MongoDB (idempotente). Não cria dados de exemplo: o banco é de
    # produção e é compartilhado com o sistema desktop.
    init_indices()

    # O agendamento NÃO roda aqui: roda no processo separado `app.worker`.

    from app.auth import exigir_login

    @app.before_request
    def guarda_de_login():
        """Primeiro guarda: sem login, nenhuma rota responde (nem consulta o banco)."""
        return exigir_login()

    @app.before_request
    def garantir_conta_ativa():
        contas = listar_contas()
        if not contas:
            session.pop("conta_ativa", None)
            return
        ids_validos = {c["id"] for c in contas}
        if session.get("conta_ativa") not in ids_validos:
            session["conta_ativa"] = contas[0]["id"]

    @app.context_processor
    def injetar_contexto_global():
        return {
            "machine_key": "cliente",
            "conta_ativa": session.get("conta_ativa"),
            "contas_disponiveis": listar_contas(),
        }

    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.contas import bp as contas_bp
    from app.routes.vendas import bp as vendas_bp
    from app.routes.agendamentos import bp as agendamentos_bp
    from app.routes.reembolso import bp as reembolso_bp
    from app.routes.ia import bp as ia_bp
    from app.routes.documentacao import bp as documentacao_bp
    from app.routes.acoes import bp as acoes_bp
    from app.routes.logs import bp as logs_bp
    from app.routes.configuracoes import bp as configuracoes_bp
    from app.routes.ml_auth import bp as ml_auth_bp
    from app.routes.solicitar import bp as solicitar_bp
    from app.routes.autorizacao import bp as autorizacao_bp
    from app.routes.cobrancas import bp as cobrancas_bp
    from app.routes.pix import bp as pix_bp
    from app.routes.encerradas import bp as encerradas_bp
    from app.routes.brindes import bp as brindes_bp
    from app.routes.dashboards import bp as dashboards_bp
    from app.routes.auth import bp as auth_bp

    for bp in (dashboard_bp, contas_bp, vendas_bp, agendamentos_bp, reembolso_bp,
               ia_bp, documentacao_bp, acoes_bp, logs_bp, configuracoes_bp, ml_auth_bp, solicitar_bp, autorizacao_bp, cobrancas_bp, pix_bp, encerradas_bp, brindes_bp, dashboards_bp, auth_bp):
        app.register_blueprint(bp)

    from flask import flash, redirect, url_for
    from app.services.controle import ParadaSolicitada

    @app.errorhandler(ParadaSolicitada)
    def parada_de_emergencia(erro):
        flash(str(erro), "danger")
        return redirect(url_for("dashboard.index", _anchor="log"))

    return app
