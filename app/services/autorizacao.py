"""
Etapa 2 — Taxar e autorizar boleto/PIX (portada do ramo `autorizar_boleto` do
desktop, dentro de `passo_1_solicitar`).

Para cada pedido elegível (boleto ainda não enviado e ainda sem autorização):
  1. Envia o aviso da taxa (valor, data de entrega e forma de pagamento).
  2. Se o aviso saiu, envia "DIGITE 1" pedindo a autorização.
  3. Se a solicitação saiu, grava a forma escolhida no pedido.

Forma de cobrança (igual ao desktop):
    pix   -> metodo_taxa='pix',    provedor_taxa=''
    mp    -> metodo_taxa='boleto', provedor_taxa='MP'
    asaas -> metodo_taxa='boleto', provedor_taxa='ASAAS'

Lote: pedidos com rastreio enviado, agrupados pelo dia do rastreio, sem
vendas encerradas. Igual ao desktop.

Textos copiados do desktop. Não reescrever.
"""
from datetime import datetime

from app.db import agora_texto, atualizar_campos_pedido, listar_pedidos
from app.services import mercadolivre
from app.services.loja import formatar_valor_br, obter_loja, parse_valor_br
from app.services.logger import log_evento

FORMAS = {
    "pix": {"metodo": "pix", "provedor": ""},
    "mp": {"metodo": "boleto", "provedor": "MP"},
    "asaas": {"metodo": "boleto", "provedor": "ASAAS"},
}

MSG_AVISO_TAXA = (
    "Olá, tudo bem?\n"
    "O seu painel importado chegou no Brasil. 🥳\n"
    "Porém, a Receita Federal taxou o seu produto no valor de R$ {valor}.\n\n"
    "É necessário realizar o pagamento desta taxa, para dar continuidade na entrega. "
    "Caso seja pago hoje, o seu pedido chegará {data_entrega} 😉\n\n"
    "{trecho_pagamento}"
)
TRECHO_PIX = (
    "O pagamento é feito exclusivamente via PIX, com a chave oficial da nossa empresa, "
    "em ambiente bancário seguro. Assim que você autorizar, enviaremos a chave PIX para pagamento."
)
TRECHO_ASAAS = (
    "O pagamento é feito exclusivamente pelo boleto da empresa que enviaremos. "
    "Assim que você autorizar, o boleto será gerado."
)
TRECHO_MP = (
    "O pagamento é feito exclusivamente pelo boleto do Mercado Pago que enviamos. "
    "A transportadora utiliza o sistema do Mercado Pago para garantir a segurança da plataforma. "
    "Assim que você autorizar, o boleto será gerado."
)
MSG_DIGITE_1_PIX = (
    "DIGITE 1\n\nPara que possamos enviar a chave PIX para pagamento da taxa "
    "e dar continuidade na entrega do seu pedido. 😉"
)
MSG_DIGITE_1_BOLETO = (
    "DIGITE 1\n\nPara que possamos gerar o boleto para pagamento da taxa "
    "e dar continuidade na entrega do seu pedido. 😉"
)


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def dia_do_rastreio(texto):
    """'25/11/2026 14:30' -> '25/11/2026'. None se não estiver no formato."""
    try:
        return datetime.strptime((texto or "")[:10], "%d/%m/%Y").strftime("%d/%m/%Y")
    except ValueError:
        return None


def texto_aviso(valor, data_entrega, forma):
    trecho = TRECHO_PIX if forma == "pix" else TRECHO_ASAAS if forma == "asaas" else TRECHO_MP
    return MSG_AVISO_TAXA.format(
        valor=formatar_valor_br(valor), data_entrega=data_entrega, trecho_pagamento=trecho
    )


def texto_digite_1(forma):
    return MSG_DIGITE_1_PIX if forma == "pix" else MSG_DIGITE_1_BOLETO


def elegivel(dados):
    return not dados.get("boleto_enviado") and not dados.get("boleto_autorizado_msg")


# ---------------------------------------------------------------------------
# Lotes
# ---------------------------------------------------------------------------
def calcular_lotes(conta):
    """Lotes por dia de rastreio, do mais antigo para o mais novo. Igual ao desktop."""
    por_dia = {}
    for order_id, dados in listar_pedidos(conta).items():
        if not dados.get("rastreio_enviado") or dados.get("encerrada"):
            continue
        dia = dia_do_rastreio(dados.get("data_rastreio"))
        if dia is None:
            continue
        por_dia.setdefault(dia, []).append(str(order_id))

    lotes = []
    for numero, dia in enumerate(sorted(por_dia, key=lambda d: datetime.strptime(d, "%d/%m/%Y")), start=1):
        ids = sorted(por_dia[dia])
        lotes.append({"numero": numero, "data_label": dia, "ids": ids, "quantidade": len(ids)})
    return lotes


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def _enviar(conta, order_id, buyer_id, texto, etapa):
    ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, texto)
    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar {etapa} — {detalhe}")
    return ok


def autorizar_lote(conta, forma, data_entrega, lote_numero=None, limite=20):
    """Envia a solicitação de autorização para os pedidos elegíveis.
    Retorna um dict com o resumo (ou {'erro': ...})."""
    if forma not in FORMAS:
        return {"erro": "Forma de cobrança inválida."}
    data_entrega = (data_entrega or "").strip()
    if not data_entrega:
        return {"erro": "Informe a data de entrega (aparece na mensagem de taxa)."}
    if limite < 1:
        return {"erro": "A quantidade deve ser pelo menos 1."}

    valor = parse_valor_br(obter_loja(conta)["valor_boleto"])
    if valor is None:
        return {"erro": "Valor do boleto inválido nas configurações da loja."}

    ids_lote = None
    if lote_numero:
        lote = next((l for l in calcular_lotes(conta) if l["numero"] == int(lote_numero)), None)
        if not lote:
            return {"erro": f"Lote {lote_numero} não encontrado."}
        ids_lote = set(lote["ids"])
        log_evento(conta, "info", f"Autorização por lote {lote_numero} ({lote['data_label']}), {lote['quantidade']} ordem(ns).")

    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if elegivel(pedidos[oid])
        and (ids_lote is None or str(oid) in ids_lote)
        and pedidos[oid].get("buyer_id")
    ]

    resumo = {"candidatos": len(candidatos), "enviadas": 0, "falhas": 0}
    for order_id in candidatos:
        if resumo["enviadas"] >= limite:
            break
        dados = pedidos[order_id]
        buyer_id = dados["buyer_id"]

        if not _enviar(conta, order_id, buyer_id, texto_aviso(valor, data_entrega, forma), "aviso de taxa"):
            resumo["falhas"] += 1
            continue
        if not _enviar(conta, order_id, buyer_id, texto_digite_1(forma), "solicitação DIGITE 1"):
            resumo["falhas"] += 1
            continue

        atualizar_campos_pedido(conta, order_id, {
            "boleto_autorizado_msg": True,
            "metodo_taxa": FORMAS[forma]["metodo"],
            "provedor_taxa": FORMAS[forma]["provedor"],
            "valor_taxa": round(valor, 2),
            "data_enviado_msg_autorizado": agora_texto(),
        })
        resumo["enviadas"] += 1
        log_evento(conta, "sucesso", f"Ordem {order_id}: solicitação de autorização de taxa enviada.")

    log_evento(
        conta, "sucesso",
        f"Autorização finalizada. Elegíveis: {resumo['candidatos']} | "
        f"Enviadas: {resumo['enviadas']} | Falhas: {resumo['falhas']}",
    )
    return resumo
