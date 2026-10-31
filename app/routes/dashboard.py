from datetime import date

from flask import Blueprint, render_template, session, url_for

from app.services.controle import parada_ativa
from app.db import (
    COLECAO_LOGS,
    COLECAO_VENDAS,
    colecao,
    contar_agendamentos_ativos,
    contar_pedidos_com,
    contar_pedidos_regex,
)

bp = Blueprint("dashboard", __name__, url_prefix="/")


def _acoes_rapidas():
    # Cards de atalho. Ações ainda não portadas apontam para Vendas.
    return [
        {"icone": "bi-chat-text", "titulo": "Mensagem personalizada", "subtitulo": "Texto para ordens escolhidas", "acao": "mensagem", "url": url_for("mensagem.index")},
        {"icone": "bi-send", "titulo": "Primeira Mensagem", "subtitulo": "Pedir telefone", "acao": "solicitar", "url": url_for("solicitar.index")},
        {"icone": "bi-shield-check", "titulo": "Taxar e Autorizar", "subtitulo": "Pedir DIGITE 1", "acao": "autorizar", "url": url_for("autorizacao.index")},
        {"icone": "bi-arrow-repeat", "titulo": "Cobranças", "subtitulo": "Erro, reenvio e dobro", "acao": "cobrancas", "url": url_for("cobrancas.index")},
        {"icone": "bi-qr-code", "titulo": "PIX", "subtitulo": "Pagos e aviso PIX → boleto", "acao": "pix", "url": url_for("pix.index")},
        {"icone": "bi-x-circle", "titulo": "Vendas Encerradas", "subtitulo": "Cancelados e não entregues", "acao": "encerradas", "url": url_for("encerradas.index")},
        {"icone": "bi-gift", "titulo": "Brindes e Reclamações", "subtitulo": "Brinde e encerramento", "acao": "brindes", "url": url_for("brindes.index")},
        {"icone": "bi-bar-chart", "titulo": "Dashboard de Vendas", "subtitulo": "Status por etapa", "acao": "dash_vendas", "url": url_for("dashboards.vendas")},
        {"icone": "bi-cash-coin", "titulo": "Boletos Pagos", "subtitulo": "Por conta e período", "acao": "dash_boletos", "url": url_for("dashboards.boletos_pagos")},
        {"icone": "bi-boxes", "titulo": "Lotes", "subtitulo": "Por data de rastreio", "acao": "dash_lotes", "url": url_for("dashboards.lotes")},
        {"icone": "bi-receipt", "titulo": "Enviar Boleto", "subtitulo": "Taxa de importação", "acao": "boleto", "url": url_for("vendas.index")},
        {"icone": "bi-truck", "titulo": "Enviar Rastreio", "subtitulo": "Código de envio", "acao": "rastreio", "url": url_for("vendas.index")},
        {"icone": "bi-chat-heart", "titulo": "Agradecimento", "subtitulo": "Pós-pagamento", "acao": "agradecimento", "url": url_for("vendas.index")},
        {"icone": "bi-arrow-repeat", "titulo": "Atualizar Pagos", "subtitulo": "Conciliação MP", "acao": "atualizar_pagos"},
        {"icone": "bi-file-earmark-excel", "titulo": "Exportar Excel", "subtitulo": "Relatório completo", "acao": "exportar", "url": url_for("vendas.exportar")},
    ]


def _calcular_kpis(conta):
    hoje = date.today().strftime("%d/%m/%Y")

    boletos_pagos_hoje = contar_pedidos_regex(conta, "data_boleto_pago", hoje)
    aguardando_autorizacao = contar_aguardando_autorizacao(conta)
    boletos_vencidos = contar_pedidos_com(conta, {"boleto_vencido": True})
    agendamentos_ativos = contar_agendamentos_ativos(conta)

    return [
        {"label": "Boletos pagos hoje", "valor": boletos_pagos_hoje, "badge": "success", "texto_badge": "Hoje"},
        {"label": "Aguardando autorização", "valor": aguardando_autorizacao, "badge": "warning", "texto_badge": "Pendente"},
        {"label": "Boletos vencidos", "valor": boletos_vencidos, "badge": "danger", "texto_badge": "Atenção"},
        {"label": "Agendamentos ativos", "valor": agendamentos_ativos, "badge": "neutral", "texto_badge": "Rodando"},
    ]


def contar_aguardando_autorizacao(conta):
    """Pedidos com autorização enviada, boleto ainda não enviado e cliente não autorizou."""
    return colecao(COLECAO_VENDAS).count_documents({
        "conta": conta,
        "dados.boleto_autorizado_msg": True,
        "dados.boleto_enviado": {"$ne": True},
        "dados.cliente_autorizou": {"$ne": True},
    })


@bp.route("/")
def index():
    conta = session.get("conta_ativa")
    kpis = _calcular_kpis(conta) if conta else []

    logs = []
    if conta:
        registros = list(
            colecao(COLECAO_LOGS)
            .find({"conta": conta}, {"nivel": 1, "mensagem": 1, "timestamp": 1})
            .sort("_id", -1)
            .limit(8)
        )
        logs = [
            {"hora": r["timestamp"].split(" ")[-1], "nivel": r["nivel"], "msg": r["mensagem"]}
            for r in reversed(registros)
        ]

    return render_template(
        "dashboard/index.html",
        active_page="dashboard",
        kpis=kpis,
        acoes=_acoes_rapidas(),
        logs=logs,
        parada=parada_ativa(),
    )
