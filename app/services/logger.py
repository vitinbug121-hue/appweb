"""
Log de ações para o usuário, gravado na coleção `logs` do MongoDB.
Alimenta o console de log do dashboard. Mensagens em português, com o número
da ordem quando houver.
"""
from datetime import datetime

from app.db import COLECAO_LOGS, colecao

NIVEIS_VALIDOS = {"info", "sucesso", "aviso", "erro"}


def log_evento(conta, nivel, mensagem):
    if nivel not in NIVEIS_VALIDOS:
        nivel = "info"
    colecao(COLECAO_LOGS).insert_one({
        "conta": conta,
        "nivel": nivel,
        "mensagem": mensagem,
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    })
