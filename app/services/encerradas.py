"""
Etapa 6 — Vendas encerradas (portada de `atualizar_vendas_encerradas` do desktop).

Varre os pedidos do vendedor no Mercado Livre e marca como `encerrada` os que:
  - foram cancelados, ou
  - tiveram o envio falhado (não entregue, devolvido, cancelado ou rejeitado), ou
  - têm mediação e o envio foi devolvido/não entregue.

Só marca pedidos que JÁ existem no banco (não cria). Nunca desmarca.

Diferença deliberada: o desktop, ao receber 404 numa página, referenciava uma
variável inexistente e travava o laço. Aqui 404 encerra a varredura e é
registrado no log.
"""
import requests

from app.db import marcar_pedido_encerrado, obter_config_conta
from app.services import mercadolivre
from app.services.controle import verificar_parada
from app.services.logger import log_evento

ML_ORDERS_SEARCH_URL = "https://api.mercadolibre.com/orders/search"
PAGINA = 50
TIMEOUT = 15
STATUS_ENVIO_FALHOU = {"not_delivered", "returned", "cancelled", "rejected"}


def pedido_encerrado(pedido):
    """Regra de classificação do desktop (função pura)."""
    if pedido.get("status") == "cancelled":
        return True
    envio = (pedido.get("shipping") or {}).get("status")
    if envio in STATUS_ENVIO_FALHOU:
        return True
    tem_mediacao = len(pedido.get("mediations") or []) > 0
    return tem_mediacao and envio in ("returned", "undelivered")


def atualizar_vendas_encerradas(conta, max_paginas=None):
    """Retorna um resumo {'analisados', 'encerrados', 'marcados'} ou {'erro': ...}."""
    seller_id = obter_config_conta(conta).get("ml_seller_id")
    if not seller_id:
        return {"erro": "Conta sem ML_SELLER_ID. Autorize a conta no Mercado Livre primeiro."}

    token = mercadolivre.renovar_access_token(conta)
    if not token:
        return {"erro": "Não foi possível obter um token válido. Autorize novamente."}

    headers = {"Authorization": f"Bearer {token}"}
    offset = 0
    paginas = 0
    analisados = 0
    encerrados = []

    log_evento(conta, "info", "Iniciando busca de vendas encerradas no Mercado Livre...")
    while True:
        verificar_parada()
        params = {"seller": seller_id, "limit": PAGINA, "offset": offset, "sort": "date_desc"}
        try:
            res = requests.get(ML_ORDERS_SEARCH_URL, headers=headers, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            log_evento(conta, "erro", f"Erro ao buscar página com offset {offset}: {e}")
            break

        if res.status_code == 404:
            log_evento(conta, "aviso", f"Página com offset {offset} não encontrada (404). Varredura encerrada.")
            break
        if res.status_code != 200:
            log_evento(conta, "erro", f"Erro na busca (status {res.status_code}). Varredura interrompida.")
            break

        dados = res.json()
        pedidos = dados.get("results", []) or []
        if not pedidos:
            break

        analisados += len(pedidos)
        encerrados.extend(p for p in pedidos if pedido_encerrado(p))

        paginas += 1
        total = (dados.get("paging") or {}).get("total", 0) or 0
        offset += PAGINA
        if offset >= total or (max_paginas and paginas >= max_paginas):
            break

    if not encerrados:
        log_evento(conta, "aviso", f"Nenhuma venda encerrada encontrada entre {analisados} pedido(s) analisado(s).")
        return {"analisados": analisados, "encerrados": 0, "marcados": 0}

    marcados = 0
    for pedido in encerrados:
        verificar_parada()
        order_id = str(pedido.get("id"))
        if marcar_pedido_encerrado(conta, order_id):
            marcados += 1
            log_evento(conta, "sucesso", f"Ordem {order_id} marcada como encerrada.")

    log_evento(conta, "sucesso",
               f"Vendas encerradas finalizado. Analisados: {analisados} | "
               f"Encerradas no ML: {len(encerrados)} | Marcadas no banco: {marcados}")
    return {"analisados": analisados, "encerrados": len(encerrados), "marcados": marcados}
