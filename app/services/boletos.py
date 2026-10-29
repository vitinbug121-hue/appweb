"""
Boletos disponíveis para envio (coleção `boletos_disponiveis`).
Portado de `buscar_proximo_boleto()` e `atualizar_status_boleto()` do desktop.
"""
from app.db import buscar_proximo_boleto, contar_boletos_disponiveis, marcar_boleto_usado

__all__ = ["buscar_proximo_boleto", "marcar_boleto_usado", "contar_boletos_disponiveis"]
