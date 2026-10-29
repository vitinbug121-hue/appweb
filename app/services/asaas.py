"""
Asaas: consulta de boletos pagos. Duas opções, como decidido:

  1. API REST (este módulo): atualizar_asaas_pagos
  2. Navegador com Selenium (services/asaas_selenium.py), sessão no perfil
     dedicado ASAAS_PERFIL_CHROME.

Os dois usam as MESMAS regras de seleção (candidatos_normal / candidatos_dobro),
portadas do desktop:
  - boleto normal: boleto_enviado, não pago, provedor ASAAS, sem PIX, com id_payment
  - boleto dobro:  cobrado_dobro, normal já pago, não pago, provedor_dobro ASAAS,
                   sem PIX dobrado, com id_payment_dobro

Situação do Asaas que conta como paga: "recebida" (confirmado pelo responsável
pelo negócio). Configurável em ASAAS_SITUACOES_PAGAS.
"""
import os

import requests

from app.db import agora_texto, atualizar_campos_pedido, listar_pedidos, provedor_boleto
from app.services.logger import log_evento
from app.services.controle import verificar_parada

URLS = {
    "sandbox": "https://sandbox.asaas.com/api/v3",
    "producao": "https://api.asaas.com/v3",
}
TIMEOUT = 15
SITUACOES_PAGAS_PADRAO = "recebida"


class AsaasErro(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Regras (funções puras)
# ---------------------------------------------------------------------------
def situacoes_pagas():
    bruto = os.environ.get("ASAAS_SITUACOES_PAGAS", SITUACOES_PAGAS_PADRAO)
    return {s.strip().lower() for s in bruto.split(",") if s.strip()}


def situacao_paga(texto):
    """Comparação exata, sem maiúsculas. Texto vazio NUNCA conta como pago
    (o desktop deixava passar por causa da comparação de substring)."""
    t = (texto or "").strip().lower()
    return bool(t) and t in situacoes_pagas()


def _pix(d):
    return str(d.get("metodo_taxa") or "").strip().lower() == "pix" or bool(d.get("cobrado_via_pix"))


def _pix_dobro(d):
    return str(d.get("metodo_cobro_dobro") or "").strip().lower() == "pix"


def candidatos_normal(pedidos):
    return [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_enviado") and not pedidos[oid].get("boleto_pago")
        and not _pix(pedidos[oid])
        and provedor_boleto(pedidos[oid].get("provedor")) == "ASAAS"
        and pedidos[oid].get("id_payment")
    ]


def candidatos_dobro(pedidos):
    return [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_pago") and pedidos[oid].get("cobrado_dobro")
        and not pedidos[oid].get("boleto_pago_dobro") and not _pix_dobro(pedidos[oid])
        and provedor_boleto(pedidos[oid].get("provedor_dobro")) == "ASAAS"
        and pedidos[oid].get("id_payment_dobro")
    ]


# ---------------------------------------------------------------------------
# Opção 1: API REST
# ---------------------------------------------------------------------------
def _config_api():
    chave = os.environ.get("ASAAS_API_KEY", "").strip()
    if not chave:
        raise AsaasErro("ASAAS_API_KEY não configurada no .env.")
    ambiente = os.environ.get("ASAAS_ENV", "sandbox").strip().lower()
    if ambiente not in URLS:
        raise AsaasErro("ASAAS_ENV deve ser 'sandbox' ou 'producao'.")
    return URLS[ambiente], chave


def consultar_situacao_api(payment_id):
    verificar_parada()
    base, chave = _config_api()
    try:
        res = requests.get(f"{base}/payments/{payment_id}", headers={"access_token": chave}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AsaasErro(f"Erro de conexão com o Asaas: {e}") from e
    if res.status_code == 404:
        return False, None
    if res.status_code != 200:
        raise AsaasErro(f"Asaas respondeu status {res.status_code}.")
    return True, res.json().get("status")


def atualizar_asaas_pagos(conta):
    """Opção API. Para o status do Asaas, situacao_paga() é usada com o texto do status."""
    try:
        _config_api()
    except AsaasErro as e:
        log_evento(conta, "erro", str(e))
        return {"erro": str(e)}

    pedidos = listar_pedidos(conta)
    normais = candidatos_normal(pedidos)
    dobros = candidatos_dobro(pedidos)
    resumo = {"verificados": len(normais) + len(dobros), "pagos": 0, "nao_encontrados": 0, "erros": 0}

    for oid, campo_id, campo_pago, campo_data in (
        *[(o, "id_payment", "boleto_pago", "data_boleto_pago") for o in normais],
        *[(o, "id_payment_dobro", "boleto_pago_dobro", "data_boleto_pago_dobro") for o in dobros],
    ):
        d = pedidos[oid]
        try:
            encontrado, status = consultar_situacao_api(d[campo_id])
        except AsaasErro as e:
            resumo["erros"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: erro ao consultar Asaas — {e}")
            continue
        if not encontrado:
            resumo["nao_encontrados"] += 1
            log_evento(conta, "aviso", f"Ordem {oid}: cobrança não encontrada no Asaas.")
            continue
        if situacao_paga(status):
            atualizar_campos_pedido(conta, oid, {campo_pago: True, campo_data: agora_texto()})
            resumo["pagos"] += 1
            log_evento(conta, "sucesso", f"Ordem {oid}: {'boleto dobro' if campo_pago.endswith('dobro') else 'boleto'} marcado como pago (Asaas API).")

    log_evento(conta, "sucesso",
               f"Asaas (API) finalizado. Verificados: {resumo['verificados']} | Pagos: {resumo['pagos']} | "
               f"Não encontrados: {resumo['nao_encontrados']} | Erros: {resumo['erros']}")
    return resumo
