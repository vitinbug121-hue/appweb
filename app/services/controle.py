"""
Parada de emergência. Um único sinal no banco (coleção `controle`, _id 'parada'),
lido pelo web e pelo worker. Quando ativo, a próxima chamada a Mercado Livre,
Mercado Pago ou Asaas levanta ParadaSolicitada e a execução para.

Não se desfaz sozinho: é preciso liberar pelo botão "Liberar execuções".
"""
from datetime import datetime

from app.db import colecao

COLECAO = "controle"
ID_PARADA = "parada"


class ParadaSolicitada(Exception):
    """Levantada quando a parada de emergência está ativa."""


def parada_ativa():
    doc = colecao(COLECAO).find_one({"_id": ID_PARADA}, {"ativa": 1})
    return bool(doc and doc.get("ativa"))


def verificar_parada():
    if parada_ativa():
        raise ParadaSolicitada("Execução interrompida pelo botão de parada de emergência.")


def ativar_parada():
    colecao(COLECAO).update_one(
        {"_id": ID_PARADA},
        {"$set": {"ativa": True, "quando": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}},
        upsert=True,
    )


def liberar_parada():
    colecao(COLECAO).update_one(
        {"_id": ID_PARADA},
        {"$set": {"ativa": False, "liberada_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}},
        upsert=True,
    )


def registrar_sinal_worker():
    """O worker chama isto a cada ciclo: prova que está rodando."""
    colecao(COLECAO).update_one(
        {"_id": "worker"}, {"$set": {"ultimo_sinal": datetime.now()}}, upsert=True
    )


def sinal_worker():
    doc = colecao(COLECAO).find_one({"_id": "worker"}, {"ultimo_sinal": 1})
    return doc.get("ultimo_sinal") if doc else None
