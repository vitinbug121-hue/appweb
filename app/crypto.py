"""
Criptografia dos tokens gravados no MongoDB (ML, Mercado Pago e reembolso).

A chave fica SOMENTE no .env, na variável TOKEN_ENCRYPTION_KEY, nunca no banco
nem no código. Sem a chave, os tokens não podem ser lidos. Guarde uma cópia
segura: se a chave for perdida ou trocada, os tokens gravados viram ilegíveis.

Gerar uma chave (uma vez):
    python -c "from app.crypto import gerar_chave; print(gerar_chave())"

Valores cifrados começam com PREFIXO. Valores sem o prefixo são tratados como
texto puro (legado) e podem ser migrados com app/scripts/criptografar_tokens.py.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

PREFIXO = "enc:v1:"
_fernet = None


def gerar_chave():
    return Fernet.generate_key().decode()


def _obter_fernet():
    global _fernet
    if _fernet is None:
        chave = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()
        if not chave:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY não configurada no .env. "
                "Gere uma com: python -c \"from app.crypto import gerar_chave; print(gerar_chave())\""
            )
        _fernet = Fernet(chave.encode())
    return _fernet


def cifrar(valor):
    if valor is None or valor == "":
        return valor
    texto = str(valor)
    if texto.startswith(PREFIXO):
        return texto
    return PREFIXO + _obter_fernet().encrypt(texto.encode()).decode()


def decifrar(valor):
    if not isinstance(valor, str) or not valor.startswith(PREFIXO):
        return valor  # legado em texto puro, ainda não migrado
    try:
        return _obter_fernet().decrypt(valor[len(PREFIXO):].encode()).decode()
    except InvalidToken:
        raise RuntimeError(
            "Não foi possível decifrar um token: TOKEN_ENCRYPTION_KEY é diferente "
            "da chave usada para gravá-lo."
        )
