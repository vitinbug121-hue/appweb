"""
Log em tempo real via Server-Sent Events (SSE) — o navegador abre uma
conexão HTTP que fica aberta, e o servidor vai empurrando (yield) cada
log novo assim que ele é gravado no banco. Sem dependência extra (SSE é
só HTTP com um `Content-Type` especial — o Flask já suporta nativamente
via generator + `Response`).

As funções `_buscar_novos_logs` e `_formatar_evento` ficam separadas do
loop infinito de `_gerar_eventos` propositalmente: são puras e fáceis de
testar isoladamente, sem precisar rodar o generator (que tem um loop
`while True` com `sleep`, e travaria um teste se chamado direto).
"""
import json
import time

from flask import Blueprint, Response, session, stream_with_context

from app.db import get_connection

bp = Blueprint("logs", __name__, url_prefix="/logs")

INTERVALO_POLL_SEGUNDOS = 2


def _obter_ultimo_id(conta_id):
    if not conta_id:
        return 0
    conn = get_connection()
    row = conn.execute("SELECT MAX(id) AS max_id FROM logs WHERE conta_id = ?", (conta_id,)).fetchone()
    conn.close()
    return row["max_id"] or 0


def _buscar_novos_logs(conta_id, ultimo_id):
    if not conta_id:
        return []
    conn = get_connection()
    novos = conn.execute(
        "SELECT id, nivel, mensagem, timestamp FROM logs WHERE conta_id = ? AND id > ? ORDER BY id",
        (conta_id, ultimo_id),
    ).fetchall()
    conn.close()
    return novos


def _formatar_evento(linha):
    payload = {
        "nivel": linha["nivel"],
        "mensagem": linha["mensagem"],
        "hora": linha["timestamp"].split(" ")[-1],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _gerar_eventos(conta_id):
    ultimo_id = _obter_ultimo_id(conta_id)
    while True:
        for linha in _buscar_novos_logs(conta_id, ultimo_id):
            ultimo_id = linha["id"]
            yield _formatar_evento(linha)
        time.sleep(INTERVALO_POLL_SEGUNDOS)


@bp.route("/stream")
def stream():
    conta_id = session.get("conta_ativa_id")
    return Response(
        stream_with_context(_gerar_eventos(conta_id)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
