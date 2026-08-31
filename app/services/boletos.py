"""
Portado de `buscar_proximo_boleto()` e `atualizar_status_boleto()` do
sistema desktop — antes lia direto de `registros_pedidos.xlsx`, agora
lê da tabela `boletos_disponiveis` (populada pelo `scripts/migrar_dados.py`
ou cadastrada manualmente).
"""
from app.db import get_connection


def buscar_proximo_boleto_disponivel(conta_id):
    """Retorna o primeiro boleto ainda não usado dessa conta, ou None."""
    conn = get_connection()
    row = conn.execute(
        """SELECT id, codigo, id_payment, horario FROM boletos_disponiveis
           WHERE conta_id = ? AND usado = 0 ORDER BY id LIMIT 1""",
        (conta_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def marcar_boleto_usado(boleto_id):
    conn = get_connection()
    conn.execute("UPDATE boletos_disponiveis SET usado = 1 WHERE id = ?", (boleto_id,))
    conn.commit()
    conn.close()


def contar_boletos_disponiveis(conta_id):
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM boletos_disponiveis WHERE conta_id = ? AND usado = 0",
        (conta_id,),
    ).fetchone()["n"]
    conn.close()
    return n
