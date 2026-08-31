"""
Ação "Responder Dúvidas ML" — portada de `processar_responder_duvidas` do
sistema desktop original: busca as perguntas sem resposta nos anúncios,
manda cada uma pra IA (Groq) usando o script cadastrado pra essa conta, e
publica a resposta de volta no Mercado Livre.
"""
from app.db import get_connection
from app.services import mercadolivre, groq_ia
from app.services.logger import log_evento

# Mesmo filtro de segurança do sistema original: pula perguntas que
# mencionem essas palavras, pra não deixar a IA responder sem supervisão.
PALAVRAS_PROIBIDAS = ["golpe", "opinião", "avaliação"]


def obter_script(conta_id, campo="script_question"):
    if campo not in ("script_reclamacao", "script_comum", "script_question"):
        return None
    conn = get_connection()
    row = conn.execute(f"SELECT {campo} FROM ia_scripts WHERE conta_id = ?", (conta_id,)).fetchone()
    conn.close()
    return row[campo] if row else None


def salvar_script(conta_id, campo, texto):
    if campo not in ("script_reclamacao", "script_comum", "script_question"):
        return
    conn = get_connection()
    existente = conn.execute("SELECT conta_id FROM ia_scripts WHERE conta_id = ?", (conta_id,)).fetchone()
    if existente:
        conn.execute(f"UPDATE ia_scripts SET {campo} = ? WHERE conta_id = ?", (texto, conta_id))
    else:
        conn.execute(f"INSERT INTO ia_scripts (conta_id, {campo}) VALUES (?, ?)", (conta_id, texto))
    conn.commit()
    conn.close()


def responder_duvidas_pendentes(conta_id):
    """Executa o fluxo completo. Retorna um dict com o resumo (respondidas/puladas/erros)."""
    script = obter_script(conta_id, "script_question")
    if not script:
        log_evento(conta_id, "erro", "Script da IA (dúvidas) não configurado para essa conta.")
        return {"respondidas": 0, "puladas": 0, "erros": 0}

    perguntas = mercadolivre.buscar_perguntas_nao_respondidas(conta_id)
    respondidas = puladas = erros = 0

    for pergunta in perguntas:
        question_id = pergunta.get("id")
        texto_pergunta = pergunta.get("text", "") or ""

        if any(palavra in texto_pergunta.lower() for palavra in PALAVRAS_PROIBIDAS):
            puladas += 1
            log_evento(conta_id, "aviso", f"Pergunta {question_id}: contém termo sensível, pulada.")
            continue

        sucesso_ia, resposta_ou_erro = groq_ia.gerar_resposta(script, texto_pergunta)
        if not sucesso_ia:
            erros += 1
            log_evento(conta_id, "erro", f"Pergunta {question_id}: erro na IA — {resposta_ou_erro}")
            continue

        sucesso_envio, detalhe = mercadolivre.responder_pergunta(conta_id, question_id, resposta_ou_erro)
        if sucesso_envio:
            respondidas += 1
            log_evento(conta_id, "sucesso", f"Pergunta {question_id} respondida pela IA.")
        else:
            erros += 1
            log_evento(conta_id, "erro", f"Pergunta {question_id}: falha ao enviar resposta — {detalhe}")

    resumo = {"respondidas": respondidas, "puladas": puladas, "erros": erros}
    log_evento(
        conta_id, "sucesso",
        f"IA Dúvidas finalizada. Respondidas: {respondidas} | Puladas: {puladas} | Erros: {erros}",
    )
    return resumo
