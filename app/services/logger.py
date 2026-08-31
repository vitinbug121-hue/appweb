"""
Log estruturado no banco (tabela `logs`), no lugar do `self.logger()`
que escrevia direto no ScrolledText do Tkinter.

Todo service que faz uma ação "real" (enviar mensagem, atualizar boleto,
etc.) deve registrar o resultado aqui — é isso que alimenta o console
de log no dashboard.
"""
from datetime import datetime

from app.db import get_connection

NIVEIS_VALIDOS = {"info", "sucesso", "aviso", "erro"}


def log_evento(conta_id, nivel, mensagem):
    if nivel not in NIVEIS_VALIDOS:
        nivel = "info"

    conn = get_connection()
    conn.execute(
        "INSERT INTO logs (conta_id, nivel, mensagem, timestamp) VALUES (?, ?, ?, ?)",
        (conta_id, nivel, mensagem, datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
    )
    conn.commit()
    conn.close()
