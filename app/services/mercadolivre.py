"""
Chamadas à API do Mercado Livre (tokens em MongoDB).

Portado do `GerenciadorTokenML` e do `enviarMsgML` do desktop, sem Tkinter.
Funções de envio devolvem (sucesso: bool, detalhe: str) e nunca lançam exceção
para quem chama.
"""
import os
from urllib.parse import parse_qs, quote, urlparse

import requests
from app.services.controle import verificar_parada

from app.db import (
    obter_config_conta,
    obter_pedido,
    obter_tokens_ml,
    salvar_config_conta,
    salvar_tokens_ml,
)

# Redirect URI fixo do aplicativo no Mercado Livre. Tem que ser idêntico ao
# cadastrado no painel de desenvolvedores. Pode ser trocado só pelo .env.
ML_REDIRECT_URI_FIXA = os.environ.get("ML_REDIRECT_URI", "").strip() or "https://engoo.com/app/daily-news"

ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
ML_MESSAGES_URL = "https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{seller_id}?tag=post_sale"
ML_QUESTIONS_SEARCH_URL = "https://api.mercadolibre.com/questions/search"
ML_ANSWERS_URL = "https://api.mercadolibre.com/answers"
ML_AUTH_URL = "https://auth.mercadolibre.com/authorization"
ML_USER_ME_URL = "https://api.mercadolibre.com/users/me"

TIMEOUT_PADRAO = 15


def renovar_access_token(conta):
    """Troca o refresh_token salvo por um access_token novo.
    Retorna o access_token (str) ou None se não foi possível renovar."""
    config = obter_config_conta(conta)
    tokens = obter_tokens_ml(conta)
    refresh_atual = tokens.get("refresh_token")

    if not config.get("ml_client_id") or not refresh_atual:
        return None

    payload = {
        "grant_type": "refresh_token",
        "client_id": config.get("ml_client_id"),
        "client_secret": config.get("ml_client_secret"),
        "refresh_token": refresh_atual,
    }

    try:
        res = requests.post(ML_TOKEN_URL, data=payload, timeout=TIMEOUT_PADRAO)
    except requests.RequestException:
        return None

    if res.status_code != 200:
        return None

    dados = res.json()
    salvar_tokens_ml(
        conta,
        dados.get("access_token"),
        dados.get("refresh_token", refresh_atual),
        str(dados.get("expires_in", "")),
    )
    return dados.get("access_token")


def chave_de_mensagem(conta, order_id, pack_id=None):
    """Como no desktop: pedidos de carrinho usam o pack_id; os demais, o order_id."""
    pack = pack_id or (obter_pedido(conta, order_id) or {}).get("pack_id")
    return str(pack) if pack else str(order_id)


def enviar_mensagem(conta, order_id, buyer_id, texto, pack_id=None):
    verificar_parada()
    """Envia uma mensagem de pós-venda para o comprador.
    Usa o pack_id do pedido quando existir (carrinho), igual ao desktop.
    Retorna (sucesso: bool, detalhe: str)."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    if not seller_id:
        return False, "Conta sem ML_SELLER_ID configurado (autorize a conta no Mercado Livre primeiro)."

    access_token = renovar_access_token(conta)
    if not access_token:
        return False, "Não foi possível obter um access_token válido — verifique as credenciais ML da conta."

    url = ML_MESSAGES_URL.format(order_id=chave_de_mensagem(conta, order_id, pack_id), seller_id=seller_id)
    payload = {
        "from": {"user_id": seller_id},
        "to": {"user_id": buyer_id},
        "text": texto,
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão com o Mercado Livre: {e}"

    if res.status_code in (200, 201):
        return True, "Mensagem enviada com sucesso."
    return False, f"Falha ao enviar (status {res.status_code}): {res.text[:200]}"


# ---------------------------------------------------------------------------
# Perguntas e respostas (ação "Responder Dúvidas ML")
# ---------------------------------------------------------------------------
def buscar_perguntas_nao_respondidas(conta):
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    if not seller_id:
        return []

    access_token = renovar_access_token(conta)
    if not access_token:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"seller_id": seller_id, "api_version": 4, "limit": 50, "offset": 0}

    try:
        res = requests.get(ML_QUESTIONS_SEARCH_URL, headers=headers, params=params, timeout=TIMEOUT_PADRAO)
    except requests.RequestException:
        return []

    if res.status_code != 200:
        return []

    perguntas = res.json().get("questions", [])
    return [p for p in perguntas if p.get("status") == "UNANSWERED"]


def responder_pergunta(conta, question_id, texto):
    verificar_parada()
    access_token = renovar_access_token(conta)
    if not access_token:
        return False, "Não foi possível obter um access_token válido."

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"question_id": question_id, "text": texto}

    try:
        res = requests.post(ML_ANSWERS_URL, json=payload, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão: {e}"

    if res.status_code in (200, 201):
        return True, "Resposta enviada com sucesso."
    return False, f"Falha ao enviar (status {res.status_code}): {res.text[:200]}"


# ---------------------------------------------------------------------------
# OAuth — autorização da conta com o Mercado Livre
# ---------------------------------------------------------------------------
def salvar_credenciais_ml(conta, client_id, client_secret):
    salvar_config_conta(conta, {
        "ml_client_id": client_id,
        "ml_client_secret": client_secret,
    })


def gerar_url_autorizacao(conta):
    client_id = obter_config_conta(conta).get("ml_client_id")
    if not client_id:
        return None
    redirect = quote(ML_REDIRECT_URI_FIXA, safe="")
    return f"{ML_AUTH_URL}?response_type=code&client_id={client_id}&redirect_uri={redirect}"


def extrair_code(texto):
    """Aceita o código puro ou a URL inteira copiada da barra de endereços."""
    bruto = (texto or "").strip()
    if not bruto:
        return None
    if bruto.startswith("http"):
        codigos = parse_qs(urlparse(bruto).query).get("code")
        return codigos[0].strip() if codigos else None
    return bruto


def obter_seller_id(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(ML_USER_ME_URL, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return None, f"Erro de conexão: {e}"

    if res.status_code != 200:
        return None, f"status {res.status_code}"

    return res.json().get("id"), None


def trocar_code_por_token(conta, code):
    """Troca o código de autorização por tokens, salva e busca o seller_id."""
    config = obter_config_conta(conta)
    if not config.get("ml_client_id") or not config.get("ml_client_secret"):
        return False, "Credenciais (Client ID/Secret) não configuradas para essa conta."

    payload = {
        "grant_type": "authorization_code",
        "client_id": config["ml_client_id"],
        "client_secret": config["ml_client_secret"],
        "code": code,
        "redirect_uri": ML_REDIRECT_URI_FIXA,
    }

    try:
        res = requests.post(ML_TOKEN_URL, data=payload, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão: {e}"

    if res.status_code != 200:
        try:
            erro = res.json()
            motivo = erro.get("error_description") or erro.get("message") or erro.get("error") or res.text[:200]
        except ValueError:
            motivo = res.text[:200]
        return False, f"Mercado Livre recusou o código (status {res.status_code}): {motivo}"

    dados = res.json()
    access_token = dados.get("access_token")
    if not access_token:
        return False, "Resposta do Mercado Livre não trouxe access_token."

    salvar_tokens_ml(
        conta,
        access_token,
        dados.get("refresh_token"),
        str(dados.get("expires_in", "")),
    )

    seller_id, erro = obter_seller_id(access_token)
    if seller_id:
        salvar_config_conta(conta, {"ml_seller_id": str(seller_id)})
        return True, f"Conta autorizada com sucesso! Seller ID: {seller_id}"

    return True, f"Tokens salvos, mas não foi possível obter o Seller ID automaticamente ({erro}). Preencha manualmente se necessário."


# ---------------------------------------------------------------------------
# Pedidos pagos e histórico de mensagens (usado pela Etapa 1: solicitar)
# ---------------------------------------------------------------------------
ML_ORDERS_SEARCH_URL = "https://api.mercadolibre.com/orders/search"
ML_PACK_MESSAGES_URL = "https://api.mercadolibre.com/messages/packs/{pack}/sellers/{seller_id}"


def buscar_pedidos_pagos(conta, offset_inicial=0, limite=20):
    """Pedidos pagos da conta, paginados (50 por requisição), no máximo `limite`.
    Não lança exceção: em caso de erro, devolve a lista parcial (ou vazia)."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    access_token = renovar_access_token(conta) if seller_id else None
    if not seller_id or not access_token:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    pedidos = []
    offset = int(offset_inicial or 0)
    while len(pedidos) < limite:
        verificar_parada()
        params = {"seller": seller_id, "order.status": "paid", "offset": offset, "limit": 50}
        try:
            res = requests.get(ML_ORDERS_SEARCH_URL, headers=headers, params=params, timeout=TIMEOUT_PADRAO)
            res.raise_for_status()
        except requests.RequestException:
            break
        dados = res.json()
        resultados = dados.get("results", [])
        if not resultados:
            break
        pedidos.extend(resultados)
        offset += 50
        if offset >= (dados.get("paging", {}).get("total", 0) or 0):
            break
    return pedidos[:limite]


def obter_conversa(conta, order_id, pack_id=None):
    verificar_parada()
    """Mensagens do chat de pós-venda (paginado), em ordem cronológica.
    Cada item: {texto, data, sender_id, is_seller}.
    Reclamações (claims) não são lidas aqui: entram na etapa de reclamações."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    access_token = renovar_access_token(conta) if seller_id else None
    if not seller_id or not access_token:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    url = ML_PACK_MESSAGES_URL.format(pack=order_id, seller_id=seller_id)
    usou_pack = False
    limit, offset, total = 10, 0, None
    conversa = []

    while True:
        params = {"tag": "post_sale", "limit": limit, "offset": offset}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_PADRAO)
        except requests.RequestException:
            break

        if res.status_code == 400 and not usou_pack and pack_id and str(pack_id) != str(order_id):
            url = ML_PACK_MESSAGES_URL.format(pack=pack_id, seller_id=seller_id)
            usou_pack = True
            continue
        if res.status_code != 200:
            break

        dados = res.json()
        msgs = dados.get("messages", []) or []
        for m in msgs:
            sender_id = (
                (m.get("from") or {}).get("user_id")
                or (m.get("sender") or {}).get("user_id")
                or m.get("sender_id")
            )
            conversa.append({
                "texto": m.get("text") or "",
                "data": m.get("message_date") or "",
                "sender_id": sender_id,
                "is_seller": str(sender_id) == str(seller_id),
            })

        total = (dados.get("paging") or {}).get("total", len(msgs) if total is None else total)
        offset += limit
        if not msgs or offset >= (total or 0):
            break

    conversa.sort(key=lambda m: m["data"])
    return conversa


# ---------------------------------------------------------------------------
# Reclamações (claims) — usadas pela IA de reclamação e pelo envio em reclamação
# ---------------------------------------------------------------------------
ML_CLAIM_MESSAGES_URL = "https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/messages"
ML_CLAIM_SEND_URL = "https://api.mercadolibre.com/post-purchase/v1/claims/{claim_id}/actions/send-message"


def obter_claim_ids(conta, order_id, pack_id=None):
    """Ids de reclamação ligados ao chat do pedido (primeira página do chat)."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    token = renovar_access_token(conta) if seller_id else None
    if not seller_id or not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    for pack in filter(None, [order_id, pack_id if pack_id and str(pack_id) != str(order_id) else None]):
        url = ML_PACK_MESSAGES_URL.format(pack=pack, seller_id=seller_id)
        try:
            res = requests.get(url, headers=headers, params={"tag": "post_sale", "limit": 10, "offset": 0}, timeout=TIMEOUT_PADRAO)
        except requests.RequestException:
            continue
        if res.status_code == 200:
            return list((res.json().get("conversation_status") or {}).get("claim_ids") or [])
    return []


def obter_mensagens_reclamacao(conta, claim_id):
    """Mensagens de uma reclamação, no mesmo formato de obter_conversa."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    token = renovar_access_token(conta) if seller_id else None
    if not seller_id or not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(ML_CLAIM_MESSAGES_URL.format(claim_id=claim_id), headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException:
        return []
    if res.status_code != 200:
        return []

    dados = res.json()
    itens = dados.get("messages") or dados.get("data") or [] if isinstance(dados, dict) else dados
    mensagens = []
    for msg in itens:
        if not isinstance(msg, dict):
            continue
        sender = msg.get("sender") if isinstance(msg.get("sender"), dict) else {}
        sender_id = sender.get("id") or sender.get("user_id") or msg.get("sender_id")
        papel = str(msg.get("sender_role") or msg.get("role") or sender.get("role") or "").lower()
        mensagens.append({
            "texto": msg.get("message") or msg.get("text") or "",
            "data": msg.get("date_created") or msg.get("message_date") or "",
            "sender_id": sender_id,
            "is_seller": str(sender_id) == str(seller_id) or papel in ("respondent", "seller"),
        })
    return mensagens


def enviar_mensagem_reclamacao(conta, claim_id, texto):
    verificar_parada()
    """Envia mensagem numa reclamação (ao comprador). Retorna (ok, detalhe)."""
    token = renovar_access_token(conta)
    if not token:
        return False, "Não foi possível obter um access_token válido."
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"receiver_role": "complainant", "message": texto}
    try:
        res = requests.post(ML_CLAIM_SEND_URL.format(claim_id=claim_id), json=payload, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão: {e}"
    if res.status_code in (200, 201):
        return True, "Mensagem de reclamação enviada."
    return False, f"Falha na reclamação (status {res.status_code}): {res.text[:200]}"
