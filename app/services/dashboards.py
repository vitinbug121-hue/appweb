"""
Etapa 9 — Dashboards (portados de `abrir_dashboard_vendas`,
`abrir_dashboard_boletos_pagos` e `abrir_dashboard_lotes` do desktop).

Funções puras para que a lógica possa ser conferida sem navegador.
A exportação para Excel já existe desde a Etapa 0 (services/exportar_excel.py).
"""
from datetime import datetime, timedelta

from app.db import COLECAO_VENDAS, colecao, listar_pedidos
from app.services import autorizacao
from app.services.loja import formatar_valor_br

# Ordem e nomes idênticos aos do desktop
ETAPAS_VENDAS = [
    "Solicitado", "Rastreio", "Boleto", "Boleto/PIX Pago",
    "Boleto Vencido", "Cobrança Dobrada", "Boleto Pago Dobro", "Vendas Encerradas",
]
VALOR_TAXA_LEGADO = 138.98
FORMATOS_DATA = ("%d/%m/%Y %H:%M", "%d/%m/%Y")


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def classificar_etapa(d):
    """Uma etapa por pedido, na mesma ordem de prioridade do desktop."""
    if d.get("encerrada"):
        return "Vendas Encerradas"
    if d.get("boleto_pago_dobro"):
        return "Boleto Pago Dobro"
    if d.get("cobrado_dobro"):
        return "Cobrança Dobrada"
    if d.get("boleto_pago") or d.get("pago_via_pix"):
        return "Boleto/PIX Pago"
    if d.get("boleto_vencido"):
        return "Boleto Vencido"
    if d.get("boleto_enviado"):
        return "Boleto"
    if d.get("rastreio_enviado"):
        return "Rastreio"
    if d.get("solicitado"):
        return "Solicitado"
    return None


def resumo_vendas(pedidos):
    """{etapa: [order_id, ...]} na ordem do desktop. `pedidos` = {order_id: dados}."""
    resumo = {etapa: [] for etapa in ETAPAS_VENDAS}
    for oid in sorted(pedidos, key=lambda x: str(x)):
        etapa = classificar_etapa(pedidos[oid])
        if etapa:
            resumo[etapa].append(str(oid))
    return resumo


def parse_data_solicitacao(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def valor_taxa_pedido(d):
    try:
        if d.get("valor_taxa") not in (None, ""):
            return float(d["valor_taxa"])
    except (TypeError, ValueError):
        pass
    return VALOR_TAXA_LEGADO


def dentro_do_periodo(data, de=None, ate=None):
    """Inclusivo nos dois extremos. Pedido sem data não passa quando há filtro."""
    if de is None and ate is None:
        return True
    if data is None:
        return False
    if de is not None and data < de:
        return False
    if ate is not None and data > ate + timedelta(days=1) - timedelta(seconds=1):
        return False
    return True


def filtrar_lote_por_termo(lotes, termo):
    termo = (termo or "").strip().lower()
    saida = []
    for lote in lotes:
        ids = [i for i in lote["ids"] if not termo or termo in str(i).lower()]
        if ids:
            saida.append({**lote, "ids": ids, "quantidade": len(ids)})
    return saida


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def dashboard_vendas(conta):
    pedidos = listar_pedidos(conta)
    resumo = resumo_vendas(pedidos)
    maximo = max((len(v) for v in resumo.values()), default=0)
    barras = [
        {"etapa": etapa, "quantidade": len(ids), "ids": ids,
         "percentual": round(len(ids) * 100 / maximo) if maximo else 0}
        for etapa, ids in resumo.items()
    ]
    return {"barras": barras, "total": sum(len(v) for v in resumo.values())}


def todas_as_contas():
    return sorted(c for c in colecao(COLECAO_VENDAS).distinct("conta") if c)


def dashboard_boletos_pagos(contas_selecionadas=None, de=None, ate=None):
    """Boletos/PIX pagos por conta, em todas as contas do banco (como o desktop)."""
    linhas = []
    for conta in todas_as_contas():
        if contas_selecionadas and conta not in contas_selecionadas:
            continue
        registros = []
        for oid, d in listar_pedidos(conta).items():
            if d.get("boleto_pago") is True or d.get("pago_via_pix") is True:
                data = parse_data_solicitacao(d.get("data_solicitacao"))
                if not dentro_do_periodo(data, de, ate):
                    continue
                registros.append({"order_id": str(oid), "data": data, "valor": valor_taxa_pedido(d)})
        if registros:
            total = sum(r["valor"] for r in registros)
            linhas.append({
                "conta": conta,
                "quantidade": len(registros),
                "total": total,
                "total_formatado": formatar_valor_br(total),
                "ids": sorted(r["order_id"] for r in registros),
            })

    maximo = max((l["quantidade"] for l in linhas), default=0)
    for l in linhas:
        l["percentual"] = round(l["quantidade"] * 100 / maximo) if maximo else 0
    total_geral = sum(l["total"] for l in linhas)
    return {
        "linhas": linhas,
        "quantidade_total": sum(l["quantidade"] for l in linhas),
        "total_geral": total_geral,
        "total_geral_formatado": formatar_valor_br(total_geral),
    }


def dashboard_lotes(conta, termo=None):
    lotes = filtrar_lote_por_termo(autorizacao.calcular_lotes(conta), termo)
    maximo = max((l["quantidade"] for l in lotes), default=0)
    for l in lotes:
        l["percentual"] = round(l["quantidade"] * 100 / maximo) if maximo else 0
    return lotes
