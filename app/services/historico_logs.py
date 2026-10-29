"""
Histórico completo de logs, com filtros e paginação.
Consulta a coleção `logs` (todos os registros, não só os recentes).
"""
import re

from app.db import COLECAO_LOGS, colecao

POR_PAGINA = 100
NIVEIS = ("sucesso", "erro", "aviso", "info")


def montar_filtro(conta=None, nivel=None, ordem=None, dia=None, texto=None, todas=False):
    """dia no formato dd/mm/aaaa. ordem é o ID do pedido (procura 'Ordem <id>')."""
    condicoes = []
    if not todas and conta:
        condicoes.append({"conta": conta})
    if nivel in NIVEIS:
        condicoes.append({"nivel": nivel})
    if ordem:
        condicoes.append({"mensagem": {"$regex": "Ordem " + re.escape(ordem.strip()) + r"(?!\d)"}})
    if dia:
        condicoes.append({"timestamp": {"$regex": "^" + re.escape(dia)}})
    if texto:
        condicoes.append({"mensagem": {"$regex": re.escape(texto.strip()), "$options": "i"}})
    return {"$and": condicoes} if condicoes else {}


def buscar(pagina=1, **filtros):
    filtro = montar_filtro(**filtros)
    pagina = max(1, int(pagina or 1))
    total = colecao(COLECAO_LOGS).count_documents(filtro)
    cursor = (
        colecao(COLECAO_LOGS)
        .find(filtro, {"_id": 0})
        .sort("_id", -1)
        .skip((pagina - 1) * POR_PAGINA)
        .limit(POR_PAGINA)
    )
    registros = list(cursor)
    paginas = max(1, -(-total // POR_PAGINA))
    return {"registros": registros, "total": total, "pagina": pagina, "paginas": paginas}
