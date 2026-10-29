"""
Etapa 1 — Solicitar (portada de `passo_1_solicitar`, bloco "solicitar").

Para cada pedido pago:
  1. Se já foi solicitado e o telefone ainda não foi capturado, procura o
     telefone nas mensagens DO COMPRADOR e agradece.
  2. Se passou 1 dia sem telefone (no máximo 2 cobranças, e só antes do
     rastreio e do boleto), cobra o telefone.
  3. Se já foi solicitado, não faz nada.
  4. Se a mensagem inicial já consta no chat do ML, só marca como solicitado.
  5. Senão, envia a mensagem inicial com o prazo informado.

Textos e regex copiados do desktop (ver constantes abaixo). Não reescrever.

Diferença deliberada: o telefone é procurado só nas mensagens do comprador.
O desktop procura em todas, inclusive nas da loja, o que pode capturar número
de rastreio como telefone.

Reclamações (executar_reclamacao) e a cópia "pack" de mensagens ficam para as
etapas de reclamações e revisão do envio.
"""
import re
import time
import unicodedata
from datetime import datetime

from app.db import agora_texto, atualizar_campos_pedido, obter_pedido
from app.services import mercadolivre
from app.services.controle import ParadaSolicitada
from app.services.logger import log_evento

# ---- Constantes geradas a partir do main.py (não editar à mão) ----
MSG_PADRAO = 'Olá, tudo bem? O frete é grátis para todo Brasil e o prazo estimado de entrega é até {prazo}. Lembrando que os produtos são importados, vem de fora do país! Vamos fazer o envio e mandar o código de rastreio. \n \nA transportadora precisa do seu telefone pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar.'
MSG_TEL_RECEBIDO_SEM_RASTREIO = 'Olá! recebemos seu telefone. Obrigado! \nVamos dar continuidade ao processo de envio do seu pedido. \nAssim que o código de rastreio estiver disponível, enviaremos para você acompanhar a entrega. 😉'
MSG_TEL_RECEBIDO_COM_RASTREIO = 'Olá! recebemos seu telefone. Obrigado!😉'
MSG_COBRAR_TELEFONE = 'Olá! Não recebemos o seu telefone. \nA transportadora precisa pra preencher os seus dados de entrega e enviar o código de rastreio pra você acompanhar.'
REGEX_TELEFONE_SRC = '(?:\\+?55\\s?)?\\(?(\\d{2})\\)?\\s*(9)?\\s*(\\d{4,5})[\\s.-]?(\\d{4})'

PARTE_MSG_PADRAO = "Olá, tudo bem? O frete é grátis para todo Brasil"
REGEX_TELEFONE = re.compile(REGEX_TELEFONE_SRC)
DIAS_PARA_COBRAR = 1
MAX_COBRANCAS = 2
PAUSA_ENTRE_PEDIDOS = 0.5


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem rede)
# ---------------------------------------------------------------------------
def extrair_telefone(texto):
    """Devolve só os dígitos do primeiro telefone encontrado no texto, ou None."""
    m = REGEX_TELEFONE.search(texto or "")
    if not m:
        return None
    bruto = "".join(g for g in m.groups() if g is not None)
    return "".join(re.findall(r"\d+", bruto)) or None


def primeiro_telefone_do_comprador(conversa):
    for m in conversa:
        if m.get("is_seller"):
            continue
        achado = extrair_telefone(m.get("texto", ""))
        if achado:
            return achado
    return None


def _normalizar(texto):
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKC", str(texto)).lower()
    return re.sub(r"\s+", " ", texto).strip()


def mensagem_existe(trecho, conversa):
    alvo = _normalizar(trecho)
    return any(alvo in _normalizar(m.get("texto", "")) for m in conversa)


def dias_desde(data_texto):
    """Dias desde uma data no formato do desktop (dd/mm/aaaa HH:MM). None se inválida."""
    try:
        return (datetime.now() - datetime.strptime(data_texto, "%d/%m/%Y %H:%M")).days
    except (TypeError, ValueError):
        return None


def dados_produto(pedido):
    """Produto, valor e cor a partir do pedido do ML (fluxo de pedido comum)."""
    def seguro(fn, padrao=""):
        try:
            return str(fn())
        except (KeyError, IndexError, TypeError):
            return padrao

    return {
        "produto": seguro(lambda: pedido["payments"][0]["reason"]),
        "valor": seguro(lambda: pedido["total_amount"]),
        "corProduto": seguro(lambda: pedido["order_items"][0]["item"]["variation_attributes"][0]["value_name"]),
    }


# ---------------------------------------------------------------------------
# Processamento de um pedido
# ---------------------------------------------------------------------------
def _enviar(conta, order_id, buyer_id, texto, etapa):
    ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, texto)
    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar {etapa} — {detalhe}")
    return ok


def processar_pedido(conta, pedido, prazo):
    """Executa a Etapa 1 para um pedido. Retorna um código do resultado:
    numero_capturado | cobranca_enviada | ja_solicitado | ja_no_chat | enviada | falha_envio | sem_acao"""
    order_id = str(pedido["id"])
    buyer_id = str((pedido.get("buyer") or {}).get("id") or "")
    pack_id = str(pedido["pack_id"]) if pedido.get("pack_id") else None
    dados = obter_pedido(conta, order_id) or {}

    # 1. Telefone do comprador
    if dados.get("solicitado") and not dados.get("numero_extraido"):
        conversa = mercadolivre.obter_conversa(conta, order_id, pack_id)
        telefone = primeiro_telefone_do_comprador(conversa)
        if telefone:
            atualizar_campos_pedido(conta, order_id, {"zap_extraido": telefone, "numero_extraido": True})
            log_evento(conta, "sucesso", f"Ordem {order_id}: telefone extraído: {telefone}")
            if not dados.get("rastreio_enviado"):
                _enviar(conta, order_id, buyer_id, MSG_TEL_RECEBIDO_SEM_RASTREIO, "agradecimento do telefone")
            elif not dados.get("boleto_enviado"):
                _enviar(conta, order_id, buyer_id, MSG_TEL_RECEBIDO_COM_RASTREIO, "agradecimento do telefone")
            return "numero_capturado"

    # 2. Cobrança do telefone (após 1 dia, no máximo 2 vezes)
    dias = dias_desde(dados.get("data_solicitacao"))
    if (
        dias is not None and dias >= DIAS_PARA_COBRAR
        and not dados.get("numero_extraido")
        and (dados.get("tentativa_") or 0) < MAX_COBRANCAS
        and not dados.get("boleto_enviado")
        and not dados.get("rastreio_enviado")
    ):
        if _enviar(conta, order_id, buyer_id, MSG_COBRAR_TELEFONE, "cobrança do telefone"):
            atualizar_campos_pedido(conta, order_id, {
                "data_solicitacao": agora_texto(),
                "tentativa_": (dados.get("tentativa_") or 0) + 1,
            })
            log_evento(conta, "info", f"Ordem {order_id}: telefone cobrado (tentativa {(dados.get('tentativa_') or 0) + 1}).")
            return "cobranca_enviada"

    # 3. Já solicitado: nada a fazer
    if dados.get("solicitado"):
        return "ja_solicitado"

    # 4. Mensagem inicial já existe no chat do ML: só registrar
    conversa = mercadolivre.obter_conversa(conta, order_id, pack_id)
    campos_base = {
        "buyer_id": buyer_id,
        "pack_id": pack_id,
        **dados_produto(pedido),
    }
    if mensagem_existe(PARTE_MSG_PADRAO, conversa):
        agora = agora_texto()
        atualizar_campos_pedido(conta, order_id, {
            **campos_base, "solicitado": True,
            "data_solicitacao": agora, "data_solicitacao_inicial": agora,
        })
        log_evento(conta, "info", f"Ordem {order_id}: mensagem já constava no chat; registrada como solicitada.")
        return "ja_no_chat"

    # 5. Envio da mensagem inicial
    texto = MSG_PADRAO.format(prazo=prazo)
    if not _enviar(conta, order_id, buyer_id, texto, "mensagem inicial"):
        return "falha_envio"

    agora = agora_texto()
    atualizar_campos_pedido(conta, order_id, {
        **campos_base, "solicitado": True,
        "data_solicitacao": agora, "data_solicitacao_inicial": agora,
    })
    log_evento(conta, "sucesso", f"Ordem {order_id}: mensagem enviada e registrada.")
    return "enviada"


def solicitar_lote(conta, prazo, offset_inicial=0, limite=20):
    """Executa a Etapa 1 em um lote de pedidos pagos. Retorna um resumo."""
    prazo = (prazo or "").strip()
    if not prazo:
        return {"erro": "Informe o prazo estimado de entrega."}

    pedidos = mercadolivre.buscar_pedidos_pagos(conta, offset_inicial, limite)
    resumo = {"total": len(pedidos), "enviadas": 0, "numeros": 0, "cobrancas": 0,
              "ja_solicitados": 0, "no_chat": 0, "falhas": 0}
    chaves = {
        "enviada": "enviadas", "numero_capturado": "numeros", "cobranca_enviada": "cobrancas",
        "ja_solicitado": "ja_solicitados", "ja_no_chat": "no_chat", "falha_envio": "falhas",
    }

    for pedido in pedidos:
        try:
            resultado = processar_pedido(conta, pedido, prazo)
        except ParadaSolicitada:
            raise
        except Exception as e:
            resultado = "falha_envio"
            log_evento(conta, "erro", f"Ordem {pedido.get('id')}: erro inesperado — {e}")
        if resultado in chaves:
            resumo[chaves[resultado]] += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(
        conta, "sucesso",
        f"Solicitar finalizado. Pedidos: {resumo['total']} | Enviadas: {resumo['enviadas']} | "
        f"Telefones capturados: {resumo['numeros']} | Cobranças: {resumo['cobrancas']} | "
        f"Já solicitados: {resumo['ja_solicitados']} | No chat: {resumo['no_chat']} | Falhas: {resumo['falhas']}",
    )
    return resumo
