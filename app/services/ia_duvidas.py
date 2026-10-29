"""
Ação "Responder Dúvidas ML" com IA (Groq). Portada de `processar_responder_duvidas`.

Bug corrigido em relação ao desktop: resposta vazia da IA faz `continue`
(pula a pergunta), não `break` (que encerrava o laço inteiro).
"""
from app.db import obter_script_ia, salvar_script_ia
from app.services import groq_ia, mercadolivre
from app.services.logger import log_evento

# Mesmo filtro de segurança do desktop: não deixar a IA responder esses assuntos.
PALAVRAS_PROIBIDAS = ["golpe", "opinião", "avaliação"]


def obter_script(conta, campo="script_question"):
    return obter_script_ia(conta, campo)


def salvar_script(conta, campo, texto):
    salvar_script_ia(conta, campo, texto)


def responder_duvidas_pendentes(conta):
    """Executa o fluxo completo. Retorna um dict com o resumo."""
    script = obter_script(conta, "script_question")
    if not script:
        log_evento(conta, "erro", "Script da IA (dúvidas) não configurado para essa conta.")
        return {"respondidas": 0, "puladas": 0, "erros": 0}

    perguntas = mercadolivre.buscar_perguntas_nao_respondidas(conta)
    respondidas = puladas = erros = 0

    for pergunta in perguntas:
        question_id = pergunta.get("id")
        texto_pergunta = pergunta.get("text", "") or ""

        if any(palavra in texto_pergunta.lower() for palavra in PALAVRAS_PROIBIDAS):
            puladas += 1
            log_evento(conta, "aviso", f"Pergunta {question_id}: contém termo sensível, pulada.")
            continue

        sucesso_ia, resposta_ou_erro = groq_ia.gerar_resposta(script, texto_pergunta)
        if not sucesso_ia:
            erros += 1
            log_evento(conta, "erro", f"Pergunta {question_id}: erro na IA — {resposta_ou_erro}")
            continue

        sucesso_envio, detalhe = mercadolivre.responder_pergunta(conta, question_id, resposta_ou_erro)
        if sucesso_envio:
            respondidas += 1
            log_evento(conta, "sucesso", f"Pergunta {question_id} respondida pela IA.")
        else:
            erros += 1
            log_evento(conta, "erro", f"Pergunta {question_id}: falha ao enviar resposta — {detalhe}")

    resumo = {"respondidas": respondidas, "puladas": puladas, "erros": erros}
    log_evento(
        conta, "sucesso",
        f"IA Dúvidas finalizada. Respondidas: {respondidas} | Puladas: {puladas} | Erros: {erros}",
    )
    return resumo
