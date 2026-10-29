"""
Migra tokens que ainda estão em texto puro para o formato cifrado.

Por padrão NÃO grava nada (dry-run): mostra quais campos seriam cifrados,
sem imprimir valores. Para gravar:

    python -m app.scripts.criptografar_tokens             # simulação
    python -m app.scripts.criptografar_tokens --executar  # grava

Antes de --executar, o script confere que cada valor cifrado volta ao original.
"""
import sys

from app.crypto import PREFIXO, cifrar, decifrar
from app.db import (
    COLECAO_CONFIG,
    COLECAO_TOKENS,
    COLECAO_TOKENS_MP,
    COLECAO_TOKENS_REEMBOLSO,
    colecao,
)

ALVOS = [
    (COLECAO_CONFIG, ["ml_client_secret"]),
    (COLECAO_TOKENS, ["access_token", "refresh_token"]),
    (COLECAO_TOKENS_MP, ["token"]),
    (COLECAO_TOKENS_REEMBOLSO, ["token"]),
]


def main(executar):
    total_docs = total_campos = 0
    for nome, campos in ALVOS:
        col = colecao(nome)
        for doc in col.find({}):
            sets = {}
            for campo in campos:
                valor = doc.get(campo)
                if isinstance(valor, str) and valor and not valor.startswith(PREFIXO):
                    cifrado = cifrar(valor)
                    if decifrar(cifrado) != valor:
                        raise RuntimeError(f"Verificação de ida e volta falhou em {nome}/{doc['_id']}.")
                    sets[campo] = cifrado
            if sets:
                total_docs += 1
                total_campos += len(sets)
                print(f"{nome} [{doc['_id']}]: campos a cifrar = {', '.join(sets)}")
                if executar:
                    col.update_one({"_id": doc["_id"]}, {"$set": sets})

    modo = "gravado" if executar else "SIMULAÇÃO (nada foi gravado)"
    print(f"{modo}: {total_campos} campo(s) em {total_docs} documento(s).")


if __name__ == "__main__":
    main(executar="--executar" in sys.argv)
