"""
Portado de `atualizar_blt_pagos` e `processar_reembolsos_pasta` do sistema
desktop original: verifica, para cada venda com boleto enviado mas ainda
não marcado como pago, se o pagamento já foi aprovado no Mercado Pago
(testando os tokens MP cadastrados da conta em carrossel); e reembolsa
pagamentos já pagos usando os tokens de reembolso COMPARTILHADOS entre
todas as contas (igual ao original).
"""
import hashlib
import time
from datetime import datetime

import requests

from app.db import get_connection
from app.services.logger import log_evento

MP_PAYMENT_URL = "https://api.mercadopago.com/v1/payments/{payment_id}"
MP_REFUND_URL = "https://api.mercadopago.com/v1/payments/{payment_id}/refunds"
TIMEOUT_PADRAO = 15
STATUS_CONSIDERADOS_PAGOS = {"approved", "refunded"}


def obter_tokens_mp(conta_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT token FROM tokens_mp WHERE conta_id = ? ORDER BY ordem", (conta_id,)
    ).fetchall()
    conn.close()
    return [r["token"] for r in rows if r["token"]]


def _consultar_pagamento(token, payment_id):
    """Retorna (encontrado: bool, status_http: int|None, status_pagamento: str|None)."""
    url = MP_PAYMENT_URL.format(payment_id=payment_id)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException:
        return False, None, None

    if res.status_code == 200:
        dados = res.json()
        return True, 200, dados.get("status")
    return False, res.status_code, None


def atualizar_pagos(conta_id):
    """Percorre as vendas com boleto enviado e ainda não pago, verifica no
    Mercado Pago e atualiza o banco. Retorna um dict com o resumo."""
    tokens = obter_tokens_mp(conta_id)
    if not tokens:
        log_evento(conta_id, "erro", "Nenhum token do Mercado Pago configurado para essa conta.")
        return {"verificados": 0, "pagos": 0, "vencidos": 0, "erros": 0}

    conn = get_connection()
    vendas = conn.execute(
        """SELECT id, order_id, id_payment FROM vendas
           WHERE conta_id = ? AND boleto_enviado = 1 AND boleto_pago = 0""",
        (conta_id,),
    ).fetchall()
    conn.close()

    pagos = vencidos = erros = 0

    for venda in vendas:
        payment_id = venda["id_payment"]
        if not payment_id:
            continue

        encontrado = False
        ultimo_status_http = None
        status_pagamento = None

        for token in tokens:
            encontrado, ultimo_status_http, status_pagamento = _consultar_pagamento(token, payment_id)
            if encontrado:
                break

        if encontrado:
            if status_pagamento in STATUS_CONSIDERADOS_PAGOS:
                conn = get_connection()
                conn.execute(
                    "UPDATE vendas SET boleto_pago = 1, data_boleto_pago = ? WHERE id = ?",
                    (datetime.now().strftime("%d/%m/%Y %H:%M"), venda["id"]),
                )
                conn.commit()
                conn.close()
                pagos += 1
                log_evento(conta_id, "sucesso", f"Ordem {venda['order_id']}: boleto marcado como pago.")
        elif ultimo_status_http == 404:
            conn = get_connection()
            conn.execute("UPDATE vendas SET boleto_vencido = 1 WHERE id = ?", (venda["id"],))
            conn.commit()
            conn.close()
            vencidos += 1
            log_evento(conta_id, "aviso", f"Ordem {venda['order_id']}: boleto não encontrado (vencido).")
        else:
            erros += 1
            log_evento(conta_id, "erro", f"Ordem {venda['order_id']}: erro ao verificar pagamento (status {ultimo_status_http}).")

    resumo = {"verificados": len(vendas), "pagos": pagos, "vencidos": vencidos, "erros": erros}
    log_evento(
        conta_id, "sucesso",
        f"Atualização finalizada. Verificados: {resumo['verificados']} | "
        f"Pagos agora: {pagos} | Vencidos: {vencidos} | Erros: {erros}",
    )
    return resumo


# ---------------------------------------------------------------------------
# REEMBOLSO — usa os tokens COMPARTILHADOS (tabela tokens_reembolso_mp),
# diferente de `atualizar_pagos` que usa os tokens da própria conta.
# ---------------------------------------------------------------------------

def obter_tokens_reembolso():
    conn = get_connection()
    rows = conn.execute(
        "SELECT token FROM tokens_reembolso_mp WHERE ativo = 1 ORDER BY ordem"
    ).fetchall()
    conn.close()
    return [r["token"] for r in rows if r["token"]]


def contar_pendentes_reembolso(conta_id):
    conn = get_connection()
    n = conn.execute(
        """SELECT COUNT(*) AS n FROM vendas
           WHERE conta_id = ? AND boleto_pago = 1 AND rembolsado = 0 AND id_payment IS NOT NULL""",
        (conta_id,),
    ).fetchone()["n"]
    conn.close()
    return n


def _tentar_reembolso(token, order_id, payment_id):
    idempotency_key = hashlib.sha256(f"{order_id}-{payment_id}-{token}-{time.time()}".encode()).hexdigest()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Idempotency-Key": idempotency_key,
    }
    url = MP_REFUND_URL.format(payment_id=payment_id)
    try:
        res = requests.post(url, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException as e:
        return False, f"Erro de conexão: {e}"

    if res.status_code in (200, 201):
        return True, "Reembolso realizado com sucesso."
    return False, f"status {res.status_code} — {res.text[:150]}"


def reembolsar_venda(conta_id, venda_id):
    """Reembolsa uma venda específica, testando os tokens compartilhados em
    carrossel. Retorna (sucesso, detalhe)."""
    tokens = obter_tokens_reembolso()
    if not tokens:
        return False, "Nenhum token de reembolso configurado (compartilhado entre as contas)."

    conn = get_connection()
    venda = conn.execute(
        "SELECT * FROM vendas WHERE id = ? AND conta_id = ?", (venda_id, conta_id)
    ).fetchone()
    conn.close()

    if not venda:
        return False, "Venda não encontrada para essa conta."
    if not venda["boleto_pago"]:
        return False, "O boleto ainda não está pago — nada para reembolsar."
    if venda["rembolsado"]:
        return False, "Essa venda já havia sido reembolsada."
    if not venda["id_payment"]:
        return False, "Venda sem id_payment registrado — não é possível reembolsar."

    ultimo_erro = None
    for token in tokens:
        sucesso, detalhe = _tentar_reembolso(token, venda["order_id"], venda["id_payment"])
        if sucesso:
            conn = get_connection()
            conn.execute(
                "UPDATE vendas SET rembolsado = 1, data_rembolso = ? WHERE id = ?",
                (datetime.now().strftime("%d/%m/%Y %H:%M"), venda_id),
            )
            conn.commit()
            conn.close()
            log_evento(conta_id, "sucesso", f"Ordem {venda['order_id']}: reembolso realizado com sucesso.")
            return True, detalhe
        ultimo_erro = detalhe

    log_evento(conta_id, "erro", f"Ordem {venda['order_id']}: falha ao reembolsar em todos os tokens testados — {ultimo_erro}")
    return False, f"Falha ao reembolsar em todos os {len(tokens)} token(s) testados — {ultimo_erro}"


# ---------------------------------------------------------------------------
# GESTÃO DE TOKENS (usado pela tela /configuracoes)
# ---------------------------------------------------------------------------

def listar_tokens_mp(conta_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, token, ordem FROM tokens_mp WHERE conta_id = ? ORDER BY ordem", (conta_id,)
    ).fetchall()
    conn.close()
    return rows


def adicionar_token_mp(conta_id, token):
    token = (token or "").strip()
    if not token:
        return
    conn = get_connection()
    maior_ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) AS m FROM tokens_mp WHERE conta_id = ?", (conta_id,)
    ).fetchone()["m"]
    conn.execute(
        "INSERT INTO tokens_mp (conta_id, token, ordem) VALUES (?, ?, ?)", (conta_id, token, maior_ordem + 1)
    )
    conn.commit()
    conn.close()


def remover_token_mp(token_id):
    conn = get_connection()
    conn.execute("DELETE FROM tokens_mp WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


def listar_tokens_reembolso_admin():
    """Versão pra tela de configuração — mostra TODOS os tokens (ativos e
    inativos), diferente de `obter_tokens_reembolso()` que só pega os ativos
    (essa é a usada de verdade na hora de reembolsar)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, token, ordem, ativo FROM tokens_reembolso_mp ORDER BY ordem"
    ).fetchall()
    conn.close()
    return rows


def adicionar_token_reembolso(token):
    token = (token or "").strip()
    if not token:
        return
    conn = get_connection()
    maior_ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) AS m FROM tokens_reembolso_mp"
    ).fetchone()["m"]
    conn.execute(
        "INSERT INTO tokens_reembolso_mp (token, ordem, ativo) VALUES (?, ?, 1)", (token, maior_ordem + 1)
    )
    conn.commit()
    conn.close()


def remover_token_reembolso(token_id):
    conn = get_connection()
    conn.execute("DELETE FROM tokens_reembolso_mp WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


def toggle_token_reembolso(token_id):
    conn = get_connection()
    row = conn.execute("SELECT ativo FROM tokens_reembolso_mp WHERE id = ?", (token_id,)).fetchone()
    if row:
        novo_estado = 0 if row["ativo"] else 1
        conn.execute("UPDATE tokens_reembolso_mp SET ativo = ? WHERE id = ?", (novo_estado, token_id))
        conn.commit()
    conn.close()
