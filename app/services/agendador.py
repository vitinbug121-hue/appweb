"""
Executor de agendamentos, rodando em background dentro do próprio processo
Flask — substitui o Windows Task Scheduler do sistema desktop original.

Implementado com um loop simples de `threading` (biblioteca padrão), em vez
de APScheduler: mesma ideia — checa periodicamente e dispara na hora certa —
mas zero dependência extra (não havia acesso à internet no ambiente onde
isso foi construído para `pip install apscheduler`). Se quiser trocar por
APScheduler no futuro (fuso horário, cron avançado, persistência de jobs),
a troca fica isolada neste arquivo — o resto do app não precisa mudar.
"""
import json
import threading
from datetime import datetime

from app.db import get_connection
from app.services import mercadopago
from app.services.logger import log_evento

INTERVALO_VERIFICACAO_SEGUNDOS = 20

# Ações que podem rodar de forma totalmente automática (sem input manual
# do usuário na hora, como um código de rastreio digitado). Só essas
# aparecem como opção no formulário de agendamento por enquanto.
ACOES_EXECUTAVEIS = {
    "atualizar_pagos": lambda conta_id: mercadopago.atualizar_pagos(conta_id),
}

ACOES_LABEL = {
    "atualizar_pagos": "Atualizar Pagos (conciliação Mercado Pago)",
}

_thread = None
_parar_evento = threading.Event()
_ja_executados = set()  # chaves (agendamento_id, horario, data) já disparadas nesse processo


def executar_agendamento(agendamento_id):
    """Executa um agendamento agora mesmo — usado tanto pelo loop automático
    quanto pelo botão "Executar agora" da interface. Grava no histórico e no log."""
    conn = get_connection()
    ag = conn.execute("SELECT * FROM agendamentos WHERE id = ?", (agendamento_id,)).fetchone()
    conn.close()

    if not ag:
        return "ERRO", "Agendamento não encontrado."

    funcao = ACOES_EXECUTAVEIS.get(ag["acao"])
    if not funcao:
        status, mensagem = "ERRO", f"Ação '{ag['acao']}' não tem execução automática implementada."
    else:
        try:
            resultado = funcao(ag["conta_id"])
            status, mensagem = "SUCESSO", f"Executado com sucesso: {resultado}"
        except Exception as e:
            status, mensagem = "ERRO", f"Erro ao executar: {e}"

    conn = get_connection()
    conn.execute(
        """INSERT INTO historico_execucao (agendamento_id, tarefa_nome, acao, status, mensagem, data_hora)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agendamento_id, ag["nome"], ag["acao"], status, mensagem, datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
    )
    conn.commit()
    conn.close()

    log_evento(ag["conta_id"], "sucesso" if status == "SUCESSO" else "erro", f"[Agendamento: {ag['nome']}] {mensagem}")
    return status, mensagem


def _verificar_e_disparar(agora=None):
    """Olha todos os agendamentos ativos e dispara os que batem com o
    horário atual. Recebe `agora` opcionalmente (facilita testar sem
    depender do relógio real da máquina)."""
    agora = agora or datetime.now()
    hora_atual = agora.strftime("%H:%M")

    conn = get_connection()
    agendamentos = conn.execute("SELECT * FROM agendamentos WHERE ativo = 1").fetchall()
    conn.close()

    for ag in agendamentos:
        try:
            horarios = json.loads(ag["horarios"] or "[]")
        except (TypeError, ValueError):
            horarios = []

        if ag["tipo"] == "unica" and ag["data"] != agora.strftime("%d/%m/%Y"):
            continue

        for horario in horarios:
            if horario != hora_atual:
                continue

            chave = (ag["id"], horario, agora.strftime("%Y-%m-%d"))
            if chave in _ja_executados:
                continue

            _ja_executados.add(chave)
            executar_agendamento(ag["id"])

            if ag["tipo"] == "unica":
                conn = get_connection()
                conn.execute("UPDATE agendamentos SET ativo = 0 WHERE id = ?", (ag["id"],))
                conn.commit()
                conn.close()


def _loop():
    while not _parar_evento.is_set():
        try:
            _verificar_e_disparar()
        except Exception as e:
            print(f"[agendador] erro no loop: {e}")
        _parar_evento.wait(INTERVALO_VERIFICACAO_SEGUNDOS)


def iniciar_agendador():
    """Inicia o loop em uma thread daemon. Seguro chamar mais de uma vez —
    só inicia de fato na primeira chamada do processo."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _parar_evento.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
