from flask import Flask, session

from app.db import init_db, seed_dados_exemplo, get_connection
from app.services import agendador


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "troque-esta-chave-em-producao"

    # ---- Banco de dados (SQLite) ----
    init_db()
    seed_dados_exemplo()

    # ---- Agendador (thread em background) ----
    agendador.iniciar_agendador()

    @app.before_request
    def garantir_conta_ativa():
        """Roda ANTES de qualquer rota. Garante que sempre exista uma
        conta ativa na sessão (a primeira cadastrada, por padrão), para
        que as rotas já encontrem session['conta_ativa_id'] pronta."""
        conn = get_connection()
        contas = conn.execute(
            "SELECT id FROM contas WHERE ativo = 1 ORDER BY email"
        ).fetchall()
        conn.close()

        if not contas:
            session.pop("conta_ativa_id", None)
            return

        ids_validos = {c["id"] for c in contas}
        if session.get("conta_ativa_id") not in ids_validos:
            session["conta_ativa_id"] = contas[0]["id"]

    @app.context_processor
    def injetar_contexto_global():
        """Deixa essas variáveis disponíveis em TODOS os templates,
        sem precisar passar em cada render_template()."""
        conn = get_connection()
        contas = conn.execute(
            "SELECT id, email FROM contas WHERE ativo = 1 ORDER BY email"
        ).fetchall()
        conn.close()

        conta_ativa_id = session.get("conta_ativa_id")
        conta_ativa_email = next(
            (c["email"] for c in contas if c["id"] == conta_ativa_id), None
        )

        return {
            "machine_key": "cliente",
            "conta_ativa": conta_ativa_email,
            "contas_disponiveis": [dict(c) for c in contas],
        }

    # ---- Blueprints ----
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

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(contas_bp)
    app.register_blueprint(vendas_bp)
    app.register_blueprint(agendamentos_bp)
    app.register_blueprint(reembolso_bp)
    app.register_blueprint(ia_bp)
    app.register_blueprint(documentacao_bp)
    app.register_blueprint(acoes_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(configuracoes_bp)
    app.register_blueprint(ml_auth_bp)

    return app
