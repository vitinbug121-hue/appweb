"""
Portado de `gerar_resposta_groq` do sistema desktop original.

Usa `requests` diretamente contra a API REST da Groq (compatível com o
formato OpenAI) em vez do SDK oficial `groq` — evita mais uma dependência
externa (o SDK é só um wrapper fino em cima dessa mesma API REST), e o
ambiente onde isso foi construído não tinha acesso à internet pra instalar
pacotes fora da biblioteca padrão.
"""
import os

import requests

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_PADRAO = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TIMEOUT_PADRAO = 90


def _obter_api_keys():
    """Coleta as chaves GROQ configuradas nas variáveis de ambiente, na
    ordem GROQ_API_KEY, GROQ_API_KEY1, GROQ_API_KEY2, ... — mesmo esquema
    do sistema original, pra rotacionar quando uma chave esgota o limite."""
    keys = []
    chave_unica = os.environ.get("GROQ_API_KEY")
    if chave_unica:
        keys.append(chave_unica)

    indice = 1
    while True:
        chave = os.environ.get(f"GROQ_API_KEY{indice}")
        if not chave:
            break
        if chave not in keys:
            keys.append(chave)
        indice += 1

    return keys


def gerar_resposta(system_text, user_text):
    """Chama a API da Groq e devolve (sucesso: bool, resposta_ou_erro: str).
    Testa as chaves em carrossel — pula pra próxima quando uma bate rate
    limit (HTTP 429), igual ao sistema original."""
    api_keys = _obter_api_keys()
    if not api_keys:
        return False, "Nenhuma chave GROQ configurada (defina GROQ_API_KEY1, GROQ_API_KEY2... no .env)."

    payload = {
        "model": GROQ_MODEL_PADRAO,
        "temperature": 0.4,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
    }

    ultimo_erro = None
    for api_key in api_keys:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            res = requests.post(GROQ_CHAT_URL, json=payload, headers=headers, timeout=TIMEOUT_PADRAO)
        except requests.RequestException as e:
            ultimo_erro = f"Erro de conexão: {e}"
            continue

        if res.status_code == 200:
            dados = res.json()
            try:
                texto = dados["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError):
                return False, "Resposta da Groq em formato inesperado."
            return True, texto

        if res.status_code == 429:
            ultimo_erro = "Rate limit (429) nessa chave, tentando a próxima..."
            continue

        return False, f"Erro na API da Groq (status {res.status_code}): {res.text[:200]}"

    return False, f"Todas as {len(api_keys)} chave(s) GROQ falharam. Último erro: {ultimo_erro}"
