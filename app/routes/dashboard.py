from datetime import date

from flask import Blueprint, render_template, session, url_for

from app.db import get_connection

bp = Blueprint("dashboard", __name__, url_prefix="/")


def _acoes_rapidas():
    # Os cards de ação continuam fixos — são atalhos de UI. A ação "rastreio"
    # já está conectada de verdade (ver app/services/rastreio.py), então
    # ela linka pra página de Vendas em vez de um placeholder.
    return [
        {"icone": "bi-receipt", "titulo": "Enviar Boleto", "subtitulo": "Taxa de importação", "acao": "boleto", "url": url_for("vendas.index")},
        {"icone": "bi-truck", "titulo": "Enviar Rastreio", "subtitulo": "Código de envio", "acao": "rastreio", "url": url_for("vendas.index")},
        {"icone": "bi-chat-heart", "titulo": "Agradecimento", "subtitulo": "Pós-pagamento", "acao": "agradecimento", "url": url_for("vendas.index")},
        {"icone": "bi-robot", "titulo": "IA Reclamação", "subtitulo": "Resposta automática", "acao": "ia_reclamacao"},
        {"icone": "bi-arrow-repeat", "titulo": "Atualizar Pagos", "subtitulo": "Conciliação MP", "acao": "atualizar_pagos", "action_url": url_for("acoes.atualizar_pagos_rota")},
        {"icone": "bi-file-earmark-excel", "titulo": "Exportar Excel", "subtitulo": "Relatório completo", "acao": "exportar", "url": url_for("vendas.exportar")},
    ]


def _calcular_kpis(conn, conta_id):
    hoje = date.today().strftime("%d/%m/%Y")

    boletos_pagos_hoje = conn.execute(
        "SELECT COUNT(*) AS n FROM vendas WHERE conta_id = ? AND boleto_pago = 1 AND data_boleto_pago LIKE ?",
        (conta_id, f"{hoje}%"),
    ).fetchone()["n"]

    aguardando_autorizacao = conn.execute(
        """SELECT COUNT(*) AS n FROM vendas
           WHERE conta_id = ? AND boleto_autorizado_msg = 1
             AND boleto_enviado = 0 AND cliente_autorizou = 0""",
        (conta_id,),
    ).fetchone()["n"]

    boletos_vencidos = conn.execute(
        "SELECT COUNT(*) AS n FROM vendas WHERE conta_id = ? AND boleto_vencido = 1",
        (conta_id,),
    ).fetchone()["n"]

    agendamentos_ativos = conn.execute(
        "SELECT COUNT(*) AS n FROM agendamentos WHERE conta_id = ? AND ativo = 1",
        (conta_id,),
    ).fetchone()["n"]

    return [
        {"label": "Boletos pagos hoje", "valor": boletos_pagos_hoje, "badge": "success", "texto_badge": "Hoje"},
        {"label": "Aguardando autorização", "valor": aguardando_autorizacao, "badge": "warning", "texto_badge": "Pendente"},
        {"label": "Boletos vencidos", "valor": boletos_vencidos, "badge": "danger", "texto_badge": "Atenção"},
        {"label": "Agendamentos ativos", "valor": agendamentos_ativos, "badge": "neutral", "texto_badge": "Rodando"},
    ]


@bp.route("/")
def index():
    conn = get_connection()

    conta_id = session.get("conta_ativa_id")
    kpis = _calcular_kpis(conn, conta_id) if conta_id else []

    logs_rows = conn.execute(
        """SELECT nivel, mensagem, timestamp FROM logs
           WHERE conta_id = ? ORDER BY id DESC LIMIT 8""",
        (conta_id,),
    ).fetchall() if conta_id else []

    conn.close()

    logs = [
        {"hora": row["timestamp"].split(" ")[-1], "nivel": row["nivel"], "msg": row["mensagem"]}
        for row in reversed(logs_rows)
    ]

    return render_template(
        "dashboard/index.html",
        active_page="dashboard",
        kpis=kpis,
        acoes=_acoes_rapidas(),
        logs=logs,
    )
