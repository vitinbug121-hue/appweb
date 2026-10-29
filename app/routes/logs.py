"""
Log em tempo real via Server-Sent Events (SSE). O navegador mantém uma conexão
HTTP aberta e o servidor envia cada log novo assim que ele é gravado.

Polling simples no MongoDB: a cada INTERVALO segundos busca logs da conta com
_id maior que o último enviado. _id do Mongo cresce com o tempo, então serve
como cursor.
"""
import json
import time

from datetime import datetime
from urllib.parse import urlencode

from flask import Blueprint, Response, render_template, request, session, stream_with_context

from app.services import historico_logs

from app.db import COLECAO_LOGS, colecao

bp = Blueprint("logs", __name__, url_prefix="/logs")

INTERVALO_POLL_SEGUNDOS = 2


def _ultimo_id(conta):
    if not conta:
        return None
    doc = colecao(COLECAO_LOGS).find_one({"conta": conta}, {"_id": 1}, sort=[("_id", -1)])
    return doc["_id"] if doc else None


def _buscar_novos_logs(conta, ultimo_id):
    if not conta:
        return []
    consulta = {"conta": conta}
    if ultimo_id is not None:
        consulta["_id"] = {"$gt": ultimo_id}
    return list(colecao(COLECAO_LOGS).find(consulta).sort("_id", 1))


def _formatar_evento(linha):
    payload = {
        "nivel": linha["nivel"],
        "mensagem": linha["mensagem"],
        "hora": linha["timestamp"].split(" ")[-1],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _gerar_eventos(conta):
    ultimo = _ultimo_id(conta)
    while True:
        for linha in _buscar_novos_logs(conta, ultimo):
            ultimo = linha["_id"]
            yield _formatar_evento(linha)
        time.sleep(INTERVALO_POLL_SEGUNDOS)


@bp.route("/stream")
def stream():
    conta = session.get("conta_ativa")
    return Response(
        stream_with_context(_gerar_eventos(conta)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/historico")
def historico():
    conta = session.get("conta_ativa")
    nivel = request.args.get("nivel", "").strip()
    ordem = request.args.get("ordem", "").strip()
    texto = request.args.get("texto", "").strip()
    dia_txt = request.args.get("dia", "").strip()
    todas = request.args.get("todas") == "on"
    try:
        pagina = max(1, int(request.args.get("pagina", "1") or 1))
    except ValueError:
        pagina = 1

    dia = None
    if dia_txt:
        try:
            dia = datetime.strptime(dia_txt, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            dia = None

    r = historico_logs.buscar(
        pagina=pagina, conta=conta, nivel=nivel or None, ordem=ordem or None,
        dia=dia, texto=texto or None, todas=todas,
    )

    # Query string sem a página, para os links de paginação
    base = urlencode({k: v for k, v in {
        "nivel": nivel, "ordem": ordem, "texto": texto, "dia": dia_txt,
        "todas": "on" if todas else "",
    }.items() if v})
    return render_template(
        "logs/historico.html",
        active_page="logs_historico",
        r=r,
        nivel=nivel, ordem=ordem, texto=texto, dia=dia_txt, todas=todas,
        base=base,
        niveis=historico_logs.NIVEIS,
    )
