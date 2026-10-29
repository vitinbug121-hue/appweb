"""
Cliente de IA: Groq (principal) com fallback para Gemini.
Portado de `gerar_resposta_groq`, `gerar_resposta_gemini`, `precisa_responder_groq`
e da verificação de intenção do desktop. Usa REST direto (sem bibliotecas extras).

Convenções:
  - gerar_resposta(system, user) -> (sucesso: bool, texto: str)   [usado pelas dúvidas]
  - gerar_resposta_ia(system, user) -> str   (lança exceção se falhar; usado pela conversa)

Chaves: GROQ_API_KEY ou GROQ_API_KEY1..N; GEMINI_API_KEY ou GEMINI_API_KEY1..N.
Modelos: GROQ_MODEL (padrão openai/gpt-oss-120b), GEMINI_MODEL (padrão gemini-2.0-flash-lite).
"""
import os
import re

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 90
TEMPERATURE = 0.1
MAX_TOKENS = 1536

_indice_groq = 0
_indice_gemini = 0


class GroqEsgotadoError(RuntimeError):
    """Todas as chaves da Groq atingiram o limite (429)."""


def _chaves(prefixo):
    chaves = []
    unica = os.environ.get(f"{prefixo}_API_KEY", "").strip()
    if unica:
        chaves.append(unica)
    i = 1
    while True:
        valor = os.environ.get(f"{prefixo}_API_KEY{i}", "").strip()
        if not valor:
            break
        if valor not in chaves:
            chaves.append(valor)
        i += 1
    return chaves


def _limpar(texto):
    """Remove blocos <think>...</think> de modelos com raciocínio."""
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.DOTALL).strip()


def _groq(system, user):
    global _indice_groq
    chaves = _chaves("GROQ")
    if not chaves:
        raise RuntimeError("Nenhuma chave GROQ configurada no .env (GROQ_API_KEY1, ...).")

    modelo = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    total = len(chaves)
    ultimo = None
    for deslocamento in range(total):
        indice = (_indice_groq + deslocamento) % total
        payload = {
            "model": modelo,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": "low",
        }
        headers = {"Authorization": f"Bearer {chaves[indice]}", "Content-Type": "application/json"}
        try:
            res = requests.post(GROQ_URL, json=payload, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise RuntimeError(f"Erro de conexão com a Groq: {e}") from e

        if res.status_code == 429:
            ultimo = res.status_code
            continue
        if res.status_code != 200:
            raise RuntimeError(f"Erro na API da Groq (status {res.status_code}): {res.text[:200]}")

        _indice_groq = indice
        conteudo = res.json()["choices"][0]["message"].get("content") or ""
        return _limpar(conteudo)

    raise GroqEsgotadoError(f"Todas as {total} chaves GROQ atingiram o limite (último status {ultimo}).")


def _gemini(system, user):
    global _indice_gemini
    chaves = _chaves("GEMINI")
    if not chaves:
        raise RuntimeError("Nenhuma chave GEMINI configurada no .env (GEMINI_API_KEY1, ...).")

    modelo = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")
    total = len(chaves)
    ultimo = None
    for deslocamento in range(total):
        indice = (_indice_gemini + deslocamento) % total
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": TEMPERATURE, "maxOutputTokens": MAX_TOKENS},
        }
        try:
            res = requests.post(
                GEMINI_URL.format(model=modelo), params={"key": chaves[indice]},
                json=payload, timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            ultimo = str(e)
            continue

        if res.status_code == 429 or res.status_code >= 500:
            ultimo = res.status_code
            continue
        if res.status_code != 200:
            raise RuntimeError(f"Erro na API do Gemini (status {res.status_code}): {res.text[:200]}")

        _indice_gemini = indice
        candidatos = res.json().get("candidates") or []
        partes = (candidatos[0].get("content") or {}).get("parts") or [] if candidatos else []
        return _limpar("".join(p.get("text", "") for p in partes))

    raise RuntimeError(f"Todas as {total} chaves GEMINI falharam (último erro: {ultimo}).")


def gerar_resposta_ia(system, user):
    """Groq primeiro; se todas as chaves estiverem esgotadas, Gemini."""
    try:
        return _groq(system, user)
    except GroqEsgotadoError:
        return _gemini(system, user)


def gerar_resposta(system, user):
    """Convenção da web: (sucesso, texto). Não lança exceção."""
    try:
        return True, gerar_resposta_ia(system, user)
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Classificadores (prompts copiados do desktop)
# ---------------------------------------------------------------------------
SYSTEM_PRECISA_RESPONDER = (
    "Você é um classificador de mensagens de atendimento ao cliente.\n"
    "Analise a mensagem enviada pelo cliente e determine se ela necessita de uma resposta.\n\n"
    "Regras:\n"
    "1. Retorne TRUE se a mensagem for uma dúvida, pergunta, solicitação, reclamação ou exigir continuidade.\n"
    "2. Retorne TRUE se o cliente informar que já pagou, quitou ou realizou algum pagamento "
    "(ex: 'já paguei', 'paguei ontem', 'fiz o pagamento'), pois isso exige confirmação/baixa por parte do vendedor.\n"
    "3. Retorne FALSE se for apenas um agradecimento, confirmação sem novidade ou despedida "
    "(ex: 'ok', 'obrigado', 'valeu', 'entendi', 'perfeito').\n"
    "4. Cliente mandou saudação como ola, oi, bom dia. Retorne TRUE.\n\n"
    "Sua resposta deve conter EXCLUSIVAMENTE a palavra TRUE ou FALSE."
)

SYSTEM_VERIFICAR_INTENCAO = (
    "Você é um classificador de intenção em um chat de atendimento ao cliente.\n"
    "O vendedor solicitou que o cliente confirme se deseja pagar a taxa de frete/envio para gerar o boleto ou receber a chave PIX.\n\n"
    "Análise das mensagens do cliente:\n"
    "Responda 'true' se o cliente demonstrar intenção de pagar ou quiser saber como pagar a taxa/frete "
    "(ex: 'vou pagar', 'como faço pra pagar', 'manda o boleto', 'manda o pix', 'quero pagar').\n"
    "Responda 'false' se o cliente recusar, disser que já pagou, pedir cancelamento ou se o texto for incerto/confuso.\n\n"
    "Responda EXCLUSIVAMENTE com 'true' ou 'false'."
)


def precisa_responder(mensagem_cliente):
    """True se a(s) mensagem(ns) do cliente exigem resposta. Lança exceção se a IA falhar."""
    resposta = gerar_resposta_ia(SYSTEM_PRECISA_RESPONDER, mensagem_cliente)
    return "TRUE" in resposta.strip().upper()


def verificar_intencao(mensagens_cliente):
    """True se o cliente quer pagar a taxa (boleto/PIX). Falha segura: False em erro."""
    if not mensagens_cliente:
        return False
    user = "Mensagens do cliente após a solicitação:\n" + "\n".join(f"- {m}" for m in mensagens_cliente)
    try:
        resposta = gerar_resposta_ia(SYSTEM_VERIFICAR_INTENCAO, user)
    except Exception:
        return False
    normalizada = (resposta or "").strip().lower()
    return normalizada.startswith("true") or normalizada.startswith("sim")
