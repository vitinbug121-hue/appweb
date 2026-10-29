"""
Etapa 4 — Cobranças de pendências (portadas dos ramos `nao_pagos` e
`nao_autorizados` do desktop, dentro de `passo_1_solicitar`).

Regras comuns:
  - Cada cobrança é enviada UMA ÚNICA VEZ por pedido (flag no pedido).
  - Só após 1 dia (janela de 24h) desde o evento de referência.

  * Não pagos: boleto enviado há mais de 1 dia, sem pagamento e sem PIX.
    Referência: data_boleto.
  * Não autorizados: DIGITE 1 enviado há mais de 1 dia, sem boleto e sem
    resposta de autorização do cliente. Referência: data_enviado_msg_autorizado.

Detecção de autorização (portada de `_e_resposta_autorizacao_1` e companhia):
  só conta a resposta do cliente APÓS o último prompt "DIGITE 1" (boleto ou
  PIX), aceitando o "1" isolado e as frases de liberação manual. O fallback
  pela IA do desktop ainda não existe na web (Etapa 7): por isso a cobrança de
  não autorizados exige confirmação explícita do operador.

Textos copiados do desktop. Não reescrever.
"""
import re
import time
from datetime import datetime, timedelta

from app.db import agora_texto, atualizar_campos_pedido, listar_pedidos
from app.services import autorizacao, brindes, groq_ia, mercadolivre
from app.services.logger import log_evento

MSG_NAO_PAGO = (
    "Olá! Identificamos que há uma taxa pendente para a liberação do seu pedido. "
    "Para que a transportadora possa dar continuidade à entrega, solicitamos o pagamento do valor informado. "
    "Caso já tenha efetuado o pagamento, por favor, desconsidere esta mensagem."
)
MSG_NAO_AUTORIZADO = (
    "Olá! Precisamos da sua autorização para dar andamento."
    "Caso não receba a confirmação, o pedido sera cancelado automaticamente. "
    "\nPara receber {item} da taxa, DIGITE 1."
)

PADRAO_PROMPT_DIGITE_1 = re.compile(
    r"digite\s*1\b.{0,150}(?:gerar o boleto|enviar a chave pix)",
    re.IGNORECASE | re.DOTALL,
)
PADRAO_MSG_COMPENSACAO = re.compile(
    r"taxa de importa[çc][ãa]o"
    r"|montagem gr[áa]tis"
    r"|est[áa]mos te presenteando"
    r"|precisamos da sua autoriza[çc][ãa]o para dar andamento"
    r"|caso n[ãa]o receba a confirma[çc][ãa]o.{0,40}cancelado automaticamente",
    re.IGNORECASE,
)
FRASES_LIBERACAO_MANUAL = (
    "a liberação do seu boleto já está sendo processada.",
    "a liberação da sua chave pix já está sendo processada.",
)
PAUSA_ENTRE_PEDIDOS = 0.5


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def _parece_codigo_boleto(texto):
    """Linha digitável tem muitos dígitos; o '1' de uma dessas partes não é resposta."""
    apenas_digitos = re.sub(r"\D", "", texto)
    if len(apenas_digitos) < 20:
        return False
    return bool(re.fullmatch(r"[\d\s.\-]+", texto))


def _e_resposta_1(texto):
    return bool(re.fullmatch(r"\s*1\s*[.!]?\s*", texto))


def cliente_autorizou(conversa):
    """True se o cliente respondeu "1" (ou frase de liberação) após o último prompt DIGITE 1."""
    ultimo = None
    for idx, m in enumerate(conversa):
        if PADRAO_PROMPT_DIGITE_1.search((m.get("texto") or "").strip()):
            ultimo = idx
    if ultimo is None:
        return False

    for m in conversa[ultimo + 1:]:
        texto = (m.get("texto") or "").strip()
        eh_frase_manual = any(f in texto.lower() for f in FRASES_LIBERACAO_MANUAL)
        if m.get("is_seller") and texto.lower() not in FRASES_LIBERACAO_MANUAL:
            continue
        if PADRAO_MSG_COMPENSACAO.search(texto):
            continue
        if _parece_codigo_boleto(texto):
            continue
        if _e_resposta_1(texto) or eh_frase_manual:
            return True
    return False


def autorizou_por_ia(conversa):
    """Fallback pela IA: mensagens do cliente após o último DIGITE 1, sem '1' isolado."""
    ultimo = None
    for idx, m in enumerate(conversa):
        if PADRAO_PROMPT_DIGITE_1.search((m.get("texto") or "").strip()):
            ultimo = idx
    if ultimo is None:
        return False
    textos = []
    for m in conversa[ultimo + 1:]:
        texto = (m.get("texto") or "").strip()
        if m.get("is_seller") or not texto:
            continue
        if PADRAO_MSG_COMPENSACAO.search(texto) or _parece_codigo_boleto(texto):
            continue
        textos.append(texto)
    return groq_ia.verificar_intencao(textos)


def _data_ou_none(texto):
    try:
        return datetime.strptime(texto, "%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return None


def _passou_um_dia(data_texto):
    data = _data_ou_none(data_texto)
    return data is not None and datetime.now() - data >= timedelta(days=1)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def cobrar_nao_pagos(conta, lote_numero=None):
    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_enviado") and not pedidos[oid].get("boleto_pago")
        and not pedidos[oid].get("pago_via_pix") and pedidos[oid].get("metodo_taxa") != "pix"
        and not pedidos[oid].get("cobranca_nao_pago_enviada") and pedidos[oid].get("buyer_id")
    ]
    if lote_numero:
        ids = _ids_do_lote(conta, lote_numero)
        if ids is None:
            return {"erro": f"Lote {lote_numero} não encontrado."}
        candidatos = [oid for oid in candidatos if str(oid) in ids]

    resumo = {"candidatos": len(candidatos), "enviadas": 0, "falhas": 0, "aguardando": 0}
    for oid in candidatos:
        dados = pedidos[oid]
        if not _passou_um_dia(dados.get("data_boleto")):
            resumo["aguardando"] += 1
            continue
        ok, detalhe = mercadolivre.enviar_mensagem(conta, oid, dados["buyer_id"], MSG_NAO_PAGO)
        if not ok:
            resumo["falhas"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: falha ao enviar cobrança de não pago — {detalhe}")
            continue
        atualizar_campos_pedido(conta, oid, {
            "cobranca_nao_pago_enviada": True,
            "data_cobranca_nao_pago": agora_texto(),
        })
        resumo["enviadas"] += 1
        log_evento(conta, "sucesso", f"Ordem {oid}: cobrança de não pago enviada.")
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(conta, "sucesso", f"Cobrança de não pagos finalizada. Enviadas: {resumo['enviadas']} | "
                                 f"Aguardando 24h: {resumo['aguardando']} | Falhas: {resumo['falhas']}")
    return resumo


def cobrar_nao_autorizados(conta, lote_numero=None):
    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_autorizado_msg") and not pedidos[oid].get("boleto_enviado")
        and not pedidos[oid].get("cliente_autorizou") and not pedidos[oid].get("cobranca_nao_autorizado_enviada")
        and pedidos[oid].get("buyer_id")
    ]
    if lote_numero:
        ids = _ids_do_lote(conta, lote_numero)
        if ids is None:
            return {"erro": f"Lote {lote_numero} não encontrado."}
        candidatos = [oid for oid in candidatos if str(oid) in ids]

    resumo = {"candidatos": len(candidatos), "enviadas": 0, "falhas": 0, "ja_autorizaram": 0, "aguardando": 0}
    for oid in candidatos:
        dados = pedidos[oid]
        ref = dados.get("data_enviado_msg_autorizado")
        if _data_ou_none(ref) and not _passou_um_dia(ref):
            resumo["aguardando"] += 1
            continue

        conversa = mercadolivre.obter_conversa(conta, oid, dados.get("pack_id"))
        if cliente_autorizou(conversa) or autorizou_por_ia(conversa):
            atualizar_campos_pedido(conta, oid, {"cliente_autorizou": True})
            resumo["ja_autorizaram"] += 1
            log_evento(conta, "info", f"Ordem {oid}: cliente já autorizou; cobrança não enviada.")
            continue

        item = "a chave PIX" if dados.get("metodo_taxa") == "pix" else "o boleto"
        ok, detalhe = mercadolivre.enviar_mensagem(conta, oid, dados["buyer_id"], MSG_NAO_AUTORIZADO.format(item=item))
        if not ok:
            resumo["falhas"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: falha ao enviar cobrança de não autorizado — {detalhe}")
            continue

        agora = agora_texto()
        atualizar_campos_pedido(conta, oid, {
            "cobranca_nao_autorizado_enviada": True,
            "ultima_cobranca_nao_autorizado": agora,
            "data_enviado_msg_autorizado": agora,
        })
        dados_brinde = {**dados, "cobranca_nao_autorizado_enviada": True}
        brindes.enviar_brinde(conta, oid, dados_brinde)
        resumo["enviadas"] += 1
        log_evento(conta, "sucesso", f"Ordem {oid}: cobrança de não autorizado enviada.")
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(conta, "sucesso",
               f"Cobrança de não autorizados finalizada. Enviadas: {resumo['enviadas']} | "
               f"Já autorizaram: {resumo['ja_autorizaram']} | Aguardando 24h: {resumo['aguardando']} | "
               f"Falhas: {resumo['falhas']}")
    return resumo


def _ids_do_lote(conta, lote_numero):
    lote = next((l for l in autorizacao.calcular_lotes(conta) if l["numero"] == int(lote_numero)), None)
    return set(lote["ids"]) if lote else None
