"""
Mercado Pago: conciliação de boletos pagos (`atualizar_pagos`) e reembolso.
Portado de `atualizar_blt_pagos` e `processar_reembolsos_pasta` do desktop.

- Conciliação usa os tokens MP da própria conta (coleção tokens_mp).
- Reembolso usa os tokens COMPARTILHADOS entre todas as contas (tokens_reembolso_mp).
"""
import hashlib
import time

import requests

from app.db import (
    agora_texto,
    atualizar_campos_pedido,
    COLECAO_VENDAS,
    colecao,
    obter_pedido,
    obter_tokens_mp,
    obter_tokens_reembolso,
)
from app.db import listar_vendas_reembolsaveis
from app.services.controle import verificar_parada
from app.services.logger import log_evento
from app.services.controle import verificar_parada

MP_PAYMENT_URL = "https://api.mercadopago.com/v1/payments/{payment_id}"
MP_REFUND_URL = "https://api.mercadopago.com/v1/payments/{payment_id}/refunds"
TIMEOUT_PADRAO = 15
STATUS_CONSIDERADOS_PAGOS = {"approved", "refunded"}


def _consultar_pagamento(token, payment_id):
    verificar_parada()
    """Retorna (encontrado: bool, status_http: int|None, status_pagamento: str|None)."""
    url = MP_PAYMENT_URL.format(payment_id=payment_id)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=TIMEOUT_PADRAO)
    except requests.RequestException:
        return False, None, None

    if res.status_code == 200:
        return True, 200, res.json().get("status")
    return False, res.status_code, None


def _vendas_aguardando_pagamento(conta):
    """Pedidos com boleto enviado e ainda não marcado como pago."""
    return list(colecao(COLECAO_VENDAS).find(
        {"conta": conta, "dados.boleto_enviado": True, "dados.boleto_pago": {"$ne": True}},
        {"_id": 0, "order_id": 1, "dados.id_payment": 1},
    ))


def atualizar_pagos(conta):
    """Verifica no Mercado Pago os boletos enviados e ainda não pagos e atualiza o banco.
    Retorna um dict com o resumo."""
    tokens = obter_tokens_mp(conta)
    if not tokens:
        log_evento(conta, "erro", "Nenhum token do Mercado Pago configurado para essa conta.")
        return {"verificados": 0, "pagos": 0, "vencidos": 0, "erros": 0}

    vendas = _vendas_aguardando_pagamento(conta)
    pagos = vencidos = erros = 0

    for venda in vendas:
        order_id = venda["order_id"]
        payment_id = venda.get("dados", {}).get("id_payment")
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
                atualizar_campos_pedido(conta, order_id, {
                    "boleto_pago": True,
                    "data_boleto_pago": agora_texto(),
                })
                pagos += 1
                log_evento(conta, "sucesso", f"Ordem {order_id}: boleto marcado como pago.")
        elif ultimo_status_http == 404:
            atualizar_campos_pedido(conta, order_id, {"boleto_vencido": True})
            vencidos += 1
            log_evento(conta, "aviso", f"Ordem {order_id}: boleto não encontrado (vencido).")
        else:
            erros += 1
            log_evento(conta, "erro", f"Ordem {order_id}: erro ao verificar pagamento (status {ultimo_status_http}).")

    resumo = {"verificados": len(vendas), "pagos": pagos, "vencidos": vencidos, "erros": erros}
    log_evento(
        conta, "sucesso",
        f"Atualização finalizada. Verificados: {resumo['verificados']} | "
        f"Pagos agora: {pagos} | Vencidos: {vencidos} | Erros: {erros}",
    )
    return resumo


# ---------------------------------------------------------------------------
# REEMBOLSO
# ---------------------------------------------------------------------------
def _tentar_reembolso(token, order_id, payment_id):
    verificar_parada()
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


def reembolsar_venda(conta, order_id):
    """Reembolsa um pedido, testando os tokens compartilhados em sequência.
    Retorna (sucesso, detalhe)."""
    tokens = obter_tokens_reembolso()
    if not tokens:
        return False, "Nenhum token de reembolso configurado (compartilhado entre as contas)."

    pedido = obter_pedido(conta, order_id)
    if pedido is None:
        return False, "Venda não encontrada para essa conta."
    if not pedido.get("boleto_pago"):
        return False, "O boleto ainda não está pago — nada para reembolsar."
    if pedido.get("rembolsado"):
        return False, "Essa venda já havia sido reembolsada."
    if not pedido.get("id_payment"):
        return False, "Venda sem id_payment registrado — não é possível reembolsar."

    ultimo_erro = None
    for token in tokens:
        sucesso, detalhe = _tentar_reembolso(token, order_id, pedido["id_payment"])
        if sucesso:
            atualizar_campos_pedido(conta, order_id, {
                "rembolsado": True,
                "data_rembolso": agora_texto(),
            })
            log_evento(conta, "sucesso", f"Ordem {order_id}: reembolso realizado com sucesso.")
            return True, detalhe
        ultimo_erro = detalhe

    log_evento(conta, "erro", f"Ordem {order_id}: falha ao reembolsar em todos os tokens testados — {ultimo_erro}")
    return False, f"Falha ao reembolsar em todos os {len(tokens)} token(s) testados — {ultimo_erro}"



def reembolsar_todos(conta):
    """Reembolsa todas as vendas elegíveis da conta, uma a uma (pode ser interrompido)."""
    pendentes = listar_vendas_reembolsaveis(conta)
    ok = falhas = 0
    for v in pendentes:
        verificar_parada()
        sucesso, _ = reembolsar_venda(conta, v["order_id"])
        ok += sucesso
        falhas += (not sucesso)
        time.sleep(0.5)
    log_evento(conta, "sucesso", f"Reembolso em lote finalizado: {ok} de {len(pendentes)} reembolsada(s), falhas: {falhas}.")
    return {"total": len(pendentes), "reembolsados": ok, "falhas": falhas}
