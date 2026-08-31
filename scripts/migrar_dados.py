"""
Migra os dados do sistema DESKTOP (Tkinter) para o banco SQLite do sistema web.

O que ele lê, por conta (cada subpasta dentro de `contas/`):
  - config_conta.json              -> tabelas `contas` + `config_conta`
  - ml_tokens_autorizacao.json     -> tabela `tokens_ml`
  - database_vendas.json           -> tabela `vendas`
  - registros_pedidos.xlsx         -> tabela `boletos_disponiveis`

E na raiz do projeto antigo (fora de `contas/`):
  - .env (TOKEN_REEMBOLSO_MP1, TOKEN_REEMBOLSO_MP2, ...) -> `tokens_reembolso_mp`

USO:
    python scripts/migrar_dados.py /caminho/para/o/projeto/antigo

O "caminho para o projeto antigo" é a pasta onde fica o `main.py` original
(a que contém a subpasta `contas/` e o `.env`).

Pode rodar quantas vezes quiser — contas e vendas já existentes são
atualizadas (não duplicadas), graças ao UNIQUE(conta_id, order_id) e
ON CONFLICT no schema.
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd

# Permite rodar `python scripts/migrar_dados.py` a partir de qualquer lugar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_connection, init_db  # noqa: E402


# ---------------------------------------------------------------------------
# Mapeamento dos campos do database_vendas.json -> colunas da tabela `vendas`
# (mesmos nomes usados no main.py original, ver classe AppColetorPro)
# ---------------------------------------------------------------------------
CAMPOS_VENDA = [
    "buyer_id", "produto", "valor", "cor_produto",
    "solicitado", "data_solicitacao", "data_solicitacao_inicial",
    "numero_extraido", "zap_extraido", "contatado_wa",
    "rastreio_enviado", "data_rastreio", "codigo_rastreio",
    "boleto_enviado", "data_boleto", "codigo_boleto", "id_payment", "horario_boleto",
    "boleto_pago", "data_boleto_pago", "boleto_pago_agradecimento", "boleto_vencido",
    "boleto_autorizado_msg", "cliente_autorizou", "cliente_autorizou_via_ia",
    "cobrado_dobro", "boleto_pago_dobro", "id_payment_dobro",
    "rembolsado", "data_rembolso",
    "encerrada", "cobranca_nao_pago_enviada",
]

# No JSON antigo o campo se chama "corProduto" (camelCase); no banco novo é
# "cor_produto" (snake_case, padrão do resto do schema). Mapeamos aqui.
ALIAS_CAMPOS_JSON = {
    "cor_produto": "corProduto",
}

# Campos que são booleanos no schema — se não existirem no JSON antigo,
# devem virar 0 (False) e não NULL, senão consultas tipo "campo = 0" quebram
# (NULL nunca é igual a 0 em SQL).
CAMPOS_BOOLEANOS = {
    "solicitado", "numero_extraido", "contatado_wa",
    "rastreio_enviado", "boleto_enviado", "boleto_pago",
    "boleto_pago_agradecimento", "boleto_vencido",
    "boleto_autorizado_msg", "cliente_autorizou", "cliente_autorizou_via_ia",
    "cobrado_dobro", "boleto_pago_dobro", "rembolsado",
    "encerrada", "cobranca_nao_pago_enviada",
}


def _bool_para_int(valor):
    return 1 if bool(valor) else 0


def migrar_conta(conn, pasta_conta, email):
    """Migra uma conta (uma subpasta de `contas/`). Retorna o conta_id."""
    config_path = os.path.join(pasta_conta, "config_conta.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    nome_exibicao = config.get("NOME_EXIBICAO") or config.get("nome") or email
    ativo = config.get("ATIVO", True)

    existente = conn.execute("SELECT id FROM contas WHERE email = ?", (email,)).fetchone()
    if existente:
        conta_id = existente["id"]
        conn.execute(
            "UPDATE contas SET nome_exibicao = ?, ativo = ? WHERE id = ?",
            (nome_exibicao, _bool_para_int(ativo), conta_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO contas (email, nome_exibicao, ativo, data_criacao) VALUES (?, ?, ?, ?)",
            (email, nome_exibicao, _bool_para_int(ativo), datetime.now().strftime("%d/%m/%Y %H:%M")),
        )
        conta_id = cur.lastrowid

    # ---- config_conta (credenciais ML) ----
    if config:
        conn.execute(
            """INSERT INTO config_conta (conta_id, ml_client_id, ml_client_secret, ml_redirect_uri, ml_seller_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(conta_id) DO UPDATE SET
                 ml_client_id = excluded.ml_client_id,
                 ml_client_secret = excluded.ml_client_secret,
                 ml_redirect_uri = excluded.ml_redirect_uri,
                 ml_seller_id = excluded.ml_seller_id""",
            (
                conta_id,
                config.get("ML_CLIENT_ID", ""),
                config.get("ML_CLIENT_SECRET", ""),
                config.get("ML_REDIRECT_URI", ""),
                config.get("ML_SELLER_ID", ""),
            ),
        )

        # tokens_mp: TOKEN_MP, TOKEN_MP2, TOKEN_MP3... presentes no config_conta.json
        conn.execute("DELETE FROM tokens_mp WHERE conta_id = ?", (conta_id,))
        ordem = 0
        for chave, valor in config.items():
            if chave.startswith("TOKEN_MP") and valor:
                conn.execute(
                    "INSERT INTO tokens_mp (conta_id, token, ordem) VALUES (?, ?, ?)",
                    (conta_id, valor, ordem),
                )
                ordem += 1

    # ---- tokens_ml (OAuth do Mercado Livre) ----
    tokens_ml_path = os.path.join(pasta_conta, "ml_tokens_autorizacao.json")
    if os.path.exists(tokens_ml_path):
        with open(tokens_ml_path, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        conn.execute(
            """INSERT INTO tokens_ml (conta_id, access_token, refresh_token, expires_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(conta_id) DO UPDATE SET
                 access_token = excluded.access_token,
                 refresh_token = excluded.refresh_token,
                 expires_at = excluded.expires_at""",
            (
                conta_id,
                tokens.get("access_token", ""),
                tokens.get("refresh_token", ""),
                tokens.get("expires_in", ""),  # o JSON original guarda segundos, não uma data — ver observação no README
            ),
        )

    return conta_id


def migrar_vendas(conn, pasta_conta, conta_id, email):
    db_path = os.path.join(pasta_conta, "database_vendas.json")
    if not os.path.exists(db_path):
        return 0

    with open(db_path, "r", encoding="utf-8") as f:
        vendas = json.load(f)

    total = 0
    for order_id, dados in vendas.items():
        valores = {}
        for campo in CAMPOS_VENDA:
            chave_json = ALIAS_CAMPOS_JSON.get(campo, campo)
            valor = dados.get(chave_json)
            # normaliza campos booleanos (o JSON antigo usa True/False do Python,
            # e às vezes o campo simplesmente não existe -> tratamos como False)
            if campo in CAMPOS_BOOLEANOS:
                valor = _bool_para_int(valor)
            valores[campo] = valor

        colunas = ", ".join(["conta_id", "order_id"] + CAMPOS_VENDA)
        placeholders = ", ".join(["?"] * (2 + len(CAMPOS_VENDA)))
        atualizacoes = ", ".join([f"{c} = excluded.{c}" for c in CAMPOS_VENDA])

        conn.execute(
            f"""INSERT INTO vendas ({colunas}) VALUES ({placeholders})
                ON CONFLICT(conta_id, order_id) DO UPDATE SET {atualizacoes}""",
            [conta_id, order_id] + [valores[c] for c in CAMPOS_VENDA],
        )
        total += 1

    print(f"  · {total} venda(s) migrada(s) para {email}")
    return total


def migrar_boletos_excel(conn, pasta_conta, conta_id, email):
    caminho_excel = os.path.join(pasta_conta, "registros_pedidos.xlsx")
    if not os.path.exists(caminho_excel):
        return 0

    try:
        df = pd.read_excel(caminho_excel)
    except Exception as e:
        print(f"  ! Erro ao ler {caminho_excel}: {e}")
        return 0

    # Evita duplicar se rodar o script mais de uma vez: limpa os boletos
    # dessa conta antes de reimportar (a planilha é a fonte da verdade).
    conn.execute("DELETE FROM boletos_disponiveis WHERE conta_id = ?", (conta_id,))

    total = 0
    for _, row in df.iterrows():
        usado = str(row.get("Boleto Usado", "False")).strip().upper() == "TRUE"
        conn.execute(
            "INSERT INTO boletos_disponiveis (conta_id, codigo, id_payment, horario, usado) VALUES (?, ?, ?, ?, ?)",
            (
                conta_id,
                str(row.get("Código", "")),
                str(row.get("id_payment", "")),
                str(row.get("Horário", "")),
                _bool_para_int(usado),
            ),
        )
        total += 1

    print(f"  · {total} boleto(s) da planilha migrado(s) para {email}")
    return total


def migrar_tokens_reembolso_raiz(conn, caminho_projeto_antigo):
    """Lê o .env da raiz do projeto antigo (fora de contas/) e importa
    os TOKEN_REEMBOLSO_MP1, TOKEN_REEMBOLSO_MP2, ... compartilhados."""
    env_path = os.path.join(caminho_projeto_antigo, ".env")
    if not os.path.exists(env_path):
        return 0

    tokens = []
    with open(env_path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chave = chave.strip()
            valor = valor.strip().strip('"').strip("'")
            if chave.startswith("TOKEN_REEMBOLSO_MP") and valor:
                tokens.append(valor)

    if not tokens:
        return 0

    conn.execute("DELETE FROM tokens_reembolso_mp")
    for ordem, token in enumerate(tokens):
        conn.execute(
            "INSERT INTO tokens_reembolso_mp (token, ordem, ativo) VALUES (?, ?, 1)",
            (token, ordem),
        )

    print(f"  · {len(tokens)} token(s) de reembolso (compartilhados) migrado(s)")
    return len(tokens)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    caminho_projeto_antigo = sys.argv[1]
    accounts_dir = os.path.join(caminho_projeto_antigo, "contas")

    if not os.path.isdir(accounts_dir):
        print(f"ERRO: não encontrei a pasta 'contas' em: {accounts_dir}")
        sys.exit(1)

    init_db()
    conn = get_connection()

    print(f"Lendo contas em: {accounts_dir}\n")

    total_contas = 0
    total_vendas = 0
    total_boletos = 0

    for nome_pasta in sorted(os.listdir(accounts_dir)):
        pasta_conta = os.path.join(accounts_dir, nome_pasta)
        if not os.path.isdir(pasta_conta):
            continue

        email = nome_pasta  # o nome da pasta É o e-mail, igual no sistema antigo
        print(f"[{email}]")

        conta_id = migrar_conta(conn, pasta_conta, email)
        total_vendas += migrar_vendas(conn, pasta_conta, conta_id, email)
        total_boletos += migrar_boletos_excel(conn, pasta_conta, conta_id, email)
        total_contas += 1
        print()

    migrar_tokens_reembolso_raiz(conn, caminho_projeto_antigo)

    conn.commit()
    conn.close()

    print("=" * 60)
    print(f"Migração concluída: {total_contas} conta(s), {total_vendas} venda(s), {total_boletos} boleto(s).")
    print("=" * 60)


if __name__ == "__main__":
    main()
