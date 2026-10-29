from flask import flash, session

from app.services import tarefas


def disparar(nome, funcao, *args, **kwargs):
    """Dispara a ação em segundo plano. Devolve False se não há conta ativa."""
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return False
    tarefas.iniciar(conta, nome, funcao, *args, **kwargs)
    flash(f"{nome} iniciado. Acompanhe o andamento no log abaixo.", "info")
    return True
