"""
Etapa 8 — Brindes e encerramento de reclamação (portados de
`enviarImagensML`, `enviar_msg_encerrar_reclamacao` e do bloco de brinde
dentro de "não autorizados" do desktop).

Brinde:
  - Enviado uma única vez por pedido, junto com a cobrança de não autorizados.
  - Texto e depois as imagens de BRINDES_DIR (jpg/jpeg/png), em uma mensagem.
  - Flag `avisoBrinde` (mesmo nome do desktop) gravado quando o TEXTO sai.
    Diferença: no desktop o flag é gravado após a cobrança, mesmo se o brinde
    falhar; aqui o brinde só é marcado quando realmente foi enviado.

Encerramento de reclamação:
  - Só em pedidos com reclamação aberta, solicitados, sem boleto enviado e sem
    autorização. No máximo 2 mensagens, com 1 dia entre elas.
  - Textos copiados do desktop.

Diferenças deliberadas:
  - Imagens: sem BRINDES_DIR configurado, o brinde sai só com texto (o desktop
    usava a pasta Brindes da máquina).
"""
import json
import os
from datetime import datetime, timedelta

import requests

from app.db import (
    agora_texto,
    atualizar_campos_pedido,
    listar_pedidos,
    obter_config_conta,
)
from app.services import mercadolivre
from app.services.loja import formatar_valor_br, obter_loja, parse_valor_br
from app.services.logger import log_evento
from app.services.controle import verificar_parada

MSG_BRINDE = (
    "Tivemos uma taxa de importação de R$ {valor}, um valor abaixo da média aplicada pela Receita Federal para esse tipo de produto.\n\n"
    "Para compensar o transtorno, estamos te presenteando com: montagem grátis, "
    "3 vasos de cerâmica, um suporte de TV e 2 puffs para sua sala!"
)
MSG_ENCERRAR_PRIMEIRA = (
    "Poderia encerrar a reclamação, Esse passo é necessário para que o sistema libere a continuidade da sua entrega."
)
MSG_ENCERRAR_SEGUNDA = (
    "Você deseja continuar ou cancelar a sua compra? Aguardamos seu retorno até amanhã para evitar o cancelamento automático."
)
EXTENSOES_IMAGEM = (".jpg", ".jpeg", ".png")
LIMITE_ENCERRAMENTOS = 2
ML_ATTACH_URL = "https://api.mercadolibre.com/messages/attachments?tag=post_sale&site_id=MLB"
ML_CLAIM_ATTACH_URL = "https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/attachments"
ML_PACK_SEND_URL = "https://api.mercadolibre.com/messages/packs/{pack}/sellers/{seller_id}?tag=post_sale"
TIMEOUT = 15


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def brinde_pendente(d):
    """Cobrança de não autorizados enviada, brinde ainda não, e comprador conhecido."""
    return bool(d.get("cobranca_nao_autorizado_enviada")) and not d.get("avisoBrinde") and bool(d.get("buyer_id"))


def mensagem_encerramento(qtd_envios):
    return MSG_ENCERRAR_PRIMEIRA if qtd_envios < 1 else MSG_ENCERRAR_SEGUNDA


def pode_encerrar(d, agora=None):
    """Regras do desktop para mandar a mensagem de encerramento de reclamação."""
    agora = agora or datetime.now()
    if d.get("boleto_enviado"):
        return False, "boleto já enviado"
    qtd = d.get("QtdenvioEncerrarReclamacao", 0) or 0
    if qtd >= LIMITE_ENCERRAMENTOS:
        return False, "limite de 2 mensagens atingido"
    ultimo = d.get("data_ultimo_envio_encerrar")
    if ultimo:
        try:
            if agora - datetime.strptime(ultimo, "%d/%m/%Y %H:%M") < timedelta(days=1):
                return False, "última mensagem há menos de 1 dia"
        except ValueError:
            pass
    return True, ""


def _valor_taxa(d, conta):
    try:
        if d.get("valor_taxa") not in (None, ""):
            return float(d["valor_taxa"])
    except (TypeError, ValueError):
        pass
    return parse_valor_br(obter_loja(conta)["valor_boleto"]) or 0.0


# ---------------------------------------------------------------------------
# Imagens
# ---------------------------------------------------------------------------
def _imagens_da_pasta(pasta):
    if not pasta or not os.path.isdir(pasta):
        return []
    return [os.path.join(pasta, f) for f in sorted(os.listdir(pasta)) if f.lower().endswith(EXTENSOES_IMAGEM)]


def _enviar_imagens(conta, order_id, buyer_id, pack_id, claim_id, arquivos):
    verificar_parada()
    token = mercadolivre.renovar_access_token(conta)
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    if not token or not seller_id:
        return False

    headers_upload = {"Authorization": f"Bearer {token}"}
    url_upload = ML_CLAIM_ATTACH_URL.format(claim_id=claim_id) if claim_id else ML_ATTACH_URL
    ids = []
    for caminho in arquivos:
        try:
            with open(caminho, "rb") as f:
                res = requests.post(url_upload, headers=headers_upload, files={"file": f}, timeout=TIMEOUT)
        except (OSError, requests.RequestException) as e:
            log_evento(conta, "erro", f"Ordem {order_id}: erro ao enviar imagem de brinde — {e}")
            continue
        if res.status_code in (200, 201):
            anexo = res.json().get("filename") or res.json().get("id")
            if anexo:
                ids.append(anexo)
        else:
            log_evento(conta, "erro", f"Ordem {order_id}: falha ao subir imagem de brinde (status {res.status_code}).")
    if not ids:
        return False

    headers_json = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if claim_id:
        url = mercadolivre.ML_CLAIM_SEND_URL.format(claim_id=claim_id)
        payload = {"receiver_role": "complainant", "message": "", "attachments": ids}
    else:
        url = ML_PACK_SEND_URL.format(pack=pack_id or order_id, seller_id=seller_id)
        payload = {"from": {"user_id": seller_id}, "to": {"user_id": buyer_id}, "text": "", "attachments": ids}
    try:
        res = requests.post(url, json=payload, headers=headers_json, timeout=TIMEOUT)
    except requests.RequestException:
        return False
    return res.status_code in (200, 201)


# ---------------------------------------------------------------------------
# Brinde
# ---------------------------------------------------------------------------
def enviar_brinde(conta, order_id, d, pasta_imagens=None):
    """Texto do brinde e, se houver, as imagens. Grava avisoBrinde se o texto saiu."""
    if d.get("avisoBrinde"):
        return True
    texto = MSG_BRINDE.format(valor=formatar_valor_br(_valor_taxa(d, conta)))
    ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, d.get("buyer_id"), texto)
    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar mensagem de brinde — {detalhe}")
        return False

    atualizar_campos_pedido(conta, order_id, {"avisoBrinde": True, "data_brinde": agora_texto()})
    log_evento(conta, "sucesso", f"Ordem {order_id}: mensagem de brinde enviada.")

    pasta = pasta_imagens or os.environ.get("BRINDES_DIR", "").strip()
    arquivos = _imagens_da_pasta(pasta)
    if arquivos:
        if _enviar_imagens(conta, order_id, d.get("buyer_id"), d.get("pack_id"), d.get("claim_id"), arquivos):
            log_evento(conta, "sucesso", f"Ordem {order_id}: imagens de brinde enviadas ({len(arquivos)}).")
        else:
            log_evento(conta, "aviso", f"Ordem {order_id}: falha ao enviar imagens de brinde.")
    return True


def enviar_brindes_pendentes(conta, limite=50):
    pedidos = listar_pedidos(conta)
    candidatos = [oid for oid in sorted(pedidos) if brinde_pendente(pedidos[oid])][:limite]
    resumo = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0}
    for oid in candidatos:
        if enviar_brinde(conta, oid, pedidos[oid]):
            resumo["enviados"] += 1
        else:
            resumo["falhas"] += 1
    log_evento(conta, "sucesso", f"Brindes finalizados. Enviados: {resumo['enviados']} | Falhas: {resumo['falhas']}")
    return resumo


# ---------------------------------------------------------------------------
# Encerramento de reclamação
# ---------------------------------------------------------------------------
def encerrar_reclamacoes(conta):
    pedidos = listar_pedidos(conta)
    candidatos = [oid for oid in sorted(pedidos)
                  if pedidos[oid].get("solicitado") and not pedidos[oid].get("boleto_enviado")
                  and not pedidos[oid].get("boleto_autorizado_msg")]

    resumo = {"candidatos": len(candidatos), "enviadas": 0, "sem_reclamacao": 0, "bloqueadas": 0, "falhas": 0}
    for oid in candidatos:
        d = pedidos[oid]
        claim_ids = mercadolivre.obter_claim_ids(conta, oid, d.get("pack_id"))
        if not claim_ids:
            resumo["sem_reclamacao"] += 1
            continue
        pode, motivo = pode_encerrar(d)
        if not pode:
            resumo["bloqueadas"] += 1
            log_evento(conta, "info", f"Ordem {oid}: encerramento não enviado ({motivo}).")
            continue

        qtd = d.get("QtdenvioEncerrarReclamacao", 0) or 0
        ok, detalhe = mercadolivre.enviar_mensagem_reclamacao(conta, str(claim_ids[0]), mensagem_encerramento(qtd))
        if not ok:
            resumo["falhas"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: falha ao pedir encerramento da reclamação — {detalhe}")
            continue

        atualizar_campos_pedido(conta, oid, {
            "QtdenvioEncerrarReclamacao": qtd + 1,
            "data_ultimo_envio_encerrar": agora_texto(),
        })
        resumo["enviadas"] += 1
        log_evento(conta, "sucesso", f"Ordem {oid}: pedido de encerramento da reclamação enviado ({qtd + 1}/2).")

    log_evento(conta, "sucesso",
               f"Encerramento de reclamações finalizado. Enviadas: {resumo['enviadas']} | "
               f"Sem reclamação: {resumo['sem_reclamacao']} | Bloqueadas: {resumo['bloqueadas']} | "
               f"Falhas: {resumo['falhas']}")
    return resumo
