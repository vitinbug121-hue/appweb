"""
Mensagem personalizada: o operador escreve um texto e escolhe as ordens.
O texto vai para o chat do comprador de cada ordem, com as quebras de linha
digitadas (no chat do Mercado Livre, cada quebra vira uma nova linha).
"""
import time

from app.db import obter_pedido
from app.services import mercadolivre
from app.services.logger import log_evento
from app.services.pix import _separar_ordens

PAUSA = 0.5


def normalizar_texto(texto):
    """Padroniza as quebras de linha (Windows usa \\r\\n) e tira espaços das pontas."""
    return (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def enviar(conta, texto, ordens_texto):
    texto = normalizar_texto(texto)
    if not texto:
        return {"erro": "Escreva a mensagem antes de enviar."}
    ordens = _separar_ordens(ordens_texto)
    if not ordens:
        return {"erro": "Informe pelo menos um número de ordem."}

    enviadas, ignoradas, falhas = [], [], []
    for oid in ordens:
        d = obter_pedido(conta, oid)
        if d is None:
            ignoradas.append((oid, "não encontrada nesta conta"))
            continue
        if not d.get("buyer_id"):
            ignoradas.append((oid, "sem comprador registrado"))
            continue
        ok, detalhe = mercadolivre.enviar_mensagem(conta, oid, d["buyer_id"], texto)
        if ok:
            enviadas.append(oid)
            log_evento(conta, "sucesso", f"Ordem {oid}: mensagem personalizada enviada.")
        else:
            falhas.append((oid, detalhe))
            log_evento(conta, "erro", f"Ordem {oid}: falha ao enviar mensagem personalizada — {detalhe}")
        time.sleep(PAUSA)

    log_evento(conta, "sucesso",
               f"Mensagem personalizada finalizada. Enviadas: {len(enviadas)} | "
               f"Ignoradas: {len(ignoradas)} | Falhas: {len(falhas)}")
    return {"enviadas": len(enviadas), "ignoradas": ignoradas, "falhas": falhas}
