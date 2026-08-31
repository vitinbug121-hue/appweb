"""
Chamadas à API do Mercado Livre.

Portado do `GerenciadorTokenML` e do `enviarMsgML` do sistema desktop
original, removendo tudo que era Tkinter (messagebox, print de debug)
e devolvendo (sucesso: bool, detalhe: str) em vez de mostrar popup.
"""
import requests

from app.db import get_connection

ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
ML_MESSAGES_URL = "https://api.mercadolibre.com/messages/packs/{order_id}/sellers/{seller_id}?tag=post_sale"

TIMEOUT_PADRAO = 15


def _obter_config_conta(conn, conta_id):
    row = conn.execute(
        "SELECT ml_client_id, ml_client_secret, ml_seller_id FROM config_conta WHERE conta_id = ?",
        (conta_id,),
    ).fetchone()
    return dict(row) if row else {}


def renovar_access_token(conta_id):
    """Troca o refresh_token salvo por um access_token novo.
    Retorna o access_token (str) ou None se não foi possível renovar
    (sem credenciais cadastradas, erro de rede, ou API recusou)."""
    conn = get_connection()
    try:
        config = _obter_config_conta(conn, conta_id)
        tokens_row = conn.execute(
            "SELECT refresh_token FROM tokens_ml WHERE conta_id = ?", (conta_id,)
        ).fetchone()

        if not config.get("ml_client_id") or not tokens_row or not tokens_row["refresh_token"]:
            return None

        payload = {
            "grant_type": "refresh_token",
            "client_id": config.get("ml_client_id"),
            "client_secret": config.get("ml_client_secret"),
            "refresh_token": tokens_row["refresh_token"],
        }

        try:
            res = requests.post(ML_TOKEN_URL, data=payload, timeout=TIMEOUT_PADRAO)
        except requests.RequestException:
            return None

        if res.status_code != 200:
            return None

        dados = res.json()
        conn.execute(
            """UPDATE tokens_ml
               SET access_token = ?, refresh_token = ?, expires_at = ?
               WHERE conta_id = ?""",
            (
                dados.get("access_token"),
                dados.get("refresh_token", tokens_row["refresh_token"]),
                str(dados.get("expires_in", "")),
                conta_id,
            ),
        )
        conn.commit()
        return dados.get("access_token")
    finally:
        conn.close()


def enviar_mensagem(conta_id, order_id, buyer_id, texto):
    """Envia uma mensagem de pós-venda para o comprador.
    Retorna (sucesso: bool, detalhe: str) — nunca lança exceção pra quem chama."""
    conn = get_connection()
    try:
        config = _obter_config_conta(conn, conta_id)
    finally:
        conn.close()

    seller_id = config.get("ml_seller_id")
    if not seller_id:
        return False, "Conta sem ML_SELLER_ID configurado (autorize a conta no Mercado Livre primeiro)."

    access_token = renovar_access_token(conta_id)
    if not access_token:
        return False, "Não foi possível obter um access_token válido — verifique as credenciais ML da conta."

    url = ML_MESSAGES_URL.format(order_id=order_id, seller_id=seller_id)
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
# Perguntas e respostas (usado pela ação "Responder Dúvidas ML" com IA)
# ---------------------------------------------------------------------------
ML_QUESTIONS_SEARCH_URL = "https://api.mercadolibre.com/questions/search"
ML_ANSWERS_URL = "https://api.mercadolibre.com/answers"


def buscar_perguntas_nao_respondidas(conta_id):
    """Retorna a lista de perguntas com status UNANSWERED nos anúncios da conta."""
    conn = get_connection()
    try:
        config = _obter_config_conta(conn, conta_id)
    finally:
        conn.close()

    seller_id = config.get("ml_seller_id")
    if not seller_id:
        return []

    access_token = renovar_access_token(conta_id)
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


def responder_pergunta(conta_id, question_id, texto):
    """Envia a resposta de uma pergunta pro Mercado Livre. Retorna (sucesso, detalhe)."""
    access_token = renovar_access_token(conta_id)
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
# OAuth — fluxo de autorização da conta com o Mercado Livre
# (portado de `fluxo_autorizacao_ml`, adaptado pro modelo web: aqui o
# próprio servidor Flask é o redirect_uri, então não precisa mais copiar
# e colar o código manualmente como no diálogo do Tkinter)
# ---------------------------------------------------------------------------
ML_AUTH_URL = "https://auth.mercadolibre.com/authorization"
ML_USER_ME_URL = "https://api.mercadolibre.com/users/me"


def salvar_credenciais_ml(conta_id, client_id, client_secret, redirect_uri):
    conn = get_connection()
    conn.execute(
        """INSERT INTO config_conta (conta_id, ml_client_id, ml_client_secret, ml_redirect_uri, ml_seller_id)
           VALUES (?, ?, ?, ?, COALESCE((SELECT ml_seller_id FROM config_conta WHERE conta_id = ?), ''))
           ON CONFLICT(conta_id) DO UPDATE SET
             ml_client_id = excluded.ml_client_id,
             ml_client_secret = excluded.ml_client_secret,
             ml_redirect_uri = excluded.ml_redirect_uri""",
        (conta_id, client_id, client_secret, redirect_uri, conta_id),
    )
    conn.commit()
    conn.close()


def gerar_url_autorizacao(conta_id, redirect_uri):
    conn = get_connection()
    config = _obter_config_conta(conn, conta_id)
    conn.close()

    client_id = config.get("ml_client_id")
    if not client_id:
        return None
    return f"{ML_AUTH_URL}?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"


def obter_seller_id(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(ML_USER_ME_URL, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return None, f"Erro de conexão: {e}"

    if res.status_code != 200:
        return None, f"status {res.status_code}"

    return res.json().get("id"), None


def trocar_code_por_token(conta_id, code, redirect_uri):
    """Troca o código de autorização (?code=... que o ML manda pro nosso
    /ml/callback) por access_token + refresh_token, salva tudo, e busca o
    seller_id. Retorna (sucesso, detalhe)."""
    conn = get_connection()
    config = _obter_config_conta(conn, conta_id)
    conn.close()

    if not config.get("ml_client_id") or not config.get("ml_client_secret"):
        return False, "Credenciais (Client ID/Secret) não configuradas para essa conta."

    payload = {
        "grant_type": "authorization_code",
        "client_id": config["ml_client_id"],
        "client_secret": config["ml_client_secret"],
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        res = requests.post(ML_TOKEN_URL, data=payload, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão: {e}"

    if res.status_code != 200:
        return False, f"Erro na troca de código (status {res.status_code}): {res.text[:200]}"

    dados = res.json()
    access_token = dados.get("access_token")
    refresh_token = dados.get("refresh_token")

    if not access_token:
        return False, "Resposta do Mercado Livre não trouxe access_token."

    conn = get_connection()
    conn.execute(
        """INSERT INTO tokens_ml (conta_id, access_token, refresh_token, expires_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(conta_id) DO UPDATE SET
             access_token = excluded.access_token,
             refresh_token = excluded.refresh_token,
             expires_at = excluded.expires_at""",
        (conta_id, access_token, refresh_token, str(dados.get("expires_in", ""))),
    )
    conn.commit()
    conn.close()

    seller_id, erro = obter_seller_id(access_token)
    if seller_id:
        conn = get_connection()
        conn.execute("UPDATE config_conta SET ml_seller_id = ? WHERE conta_id = ?", (str(seller_id), conta_id))
        conn.commit()
        conn.close()
        return True, f"Conta autorizada com sucesso! Seller ID: {seller_id}"

    return True, f"Tokens salvos, mas não foi possível obter o Seller ID automaticamente ({erro}). Preencha manualmente se necessário."
