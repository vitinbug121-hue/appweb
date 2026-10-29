"""
Carrega o arquivo .env da raiz do projeto para os.environ.

Feito sem dependências extras. Regras:
- Linhas vazias e comentários (#) são ignorados.
- Variáveis já definidas no ambiente NÃO são sobrescritas.
- Aspas simples ou duplas em volta do valor são removidas.
"""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_env(caminho=None):
    caminho = caminho or os.path.join(RAIZ, ".env")
    if not os.path.isfile(caminho):
        return False
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            chave = chave.strip()
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
                valor = valor[1:-1]
            if chave and chave not in os.environ:
                os.environ[chave] = valor
    return True
