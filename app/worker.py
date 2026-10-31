"""
Worker de agendamentos: processo SEPARADO e ÚNICO.

Rodar com:  python -m app.worker
Não rodar mais de uma instância deste processo.

A cada INTERVALO segundos verifica os agendamentos ativos (coleção
`agendamentos`) e dispara os que batem com o horário. Cada disparo é reservado
no banco antes de executar (índice único em `agendamento_execucoes`), então
reinícios ou duas instâncias acidentais não executam duas vezes.
"""
import json
import time
from datetime import datetime, timedelta

from app.db import (
    COLECAO_AGENDAMENTOS,
    colecao,
    init_indices,
    reservar_execucao,
)
from app.services.acoes_agendamento import executar_agendamento_bruto
from app.services.controle import registrar_sinal_worker

INTERVALO_SEGUNDOS = 20
# Um agendamento dispara se o horário passou há no máximo esta janela.
# Assim, se o worker reiniciar logo depois do horário, a execução não se perde.
JANELA_MINUTOS = 5


def _horario_vencido(horario, agora):
    """True se o horário HH:MM já chegou e ainda está dentro da janela."""
    try:
        h, m = (int(x) for x in horario.split(":"))
    except (AttributeError, ValueError):
        return False
    alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    return timedelta(0) <= agora - alvo < timedelta(minutes=JANELA_MINUTOS)


def _horarios_do(ag):
    """Aceita lista (formato atual) ou JSON em texto (formato antigo)."""
    h = ag.get("horarios") or []
    if isinstance(h, str):
        try:
            h = json.loads(h or "[]")
        except ValueError:
            h = []
    return h


def verificar_e_disparar(agora=None):
    agora = agora or datetime.now()
    hora_atual = agora.strftime("%H:%M")
    data_hoje = agora.strftime("%d/%m/%Y")

    for ag in colecao(COLECAO_AGENDAMENTOS).find({"ativo": True}):
        if ag.get("tipo") == "unica" and ag.get("data") != data_hoje:
            continue

        for horario in _horarios_do(ag):
            if not _horario_vencido(horario, agora):
                continue
            if not reservar_execucao(ag["_id"], horario, data_hoje):
                continue

            executar_agendamento_bruto(ag)

            if ag.get("tipo") == "unica":
                colecao(COLECAO_AGENDAMENTOS).update_one(
                    {"_id": ag["_id"]}, {"$set": {"ativo": False}}
                )


def main():
    init_indices()
    print(f"[worker] iniciado. Verificando agendamentos a cada {INTERVALO_SEGUNDOS}s.")
    while True:
        try:
            verificar_e_disparar()
        except Exception as e:
            print(f"[worker] erro no loop: {e}")
        try:
            registrar_sinal_worker()
        except Exception as e:
            print(f"[worker] não consegui registrar sinal de vida: {e}")
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    main()
