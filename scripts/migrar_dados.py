"""
Migra os dados do sistema DESKTOP (Tkinter) para o banco PostgreSQL (Railway) do sistema web.

USO:
    python scripts/migrar_dados.py /caminho/para/o/projeto/antigo
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# Permite rodar `python scripts/migrar_dados.py` a partir de qualquer lugar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_connection, init_db  # noqa: E402


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

ALIAS_CAMPOS_JSON = {
    "cor_produto": "corProduto",
}

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


def migrar_conta(cursor, pasta_conta, email):
    """Migra uma conta (uma subpasta de `contas/`). Retorna o conta_id."""
    config_path = os.path.join(pasta_conta, "config_conta.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    nome_exibicao = config.get("NOME_EXIBICAO") or config.get("nome") or email
    ativo = config.get("ATIVO", True)

    cursor.execute("SELECT id FROM contas WHERE email = %s", (email,))
    existente = cursor.fetchone()
    
    if existente:
        conta_id = existente["id"]
        cursor.execute(
            "UPDATE contas SET nome_exibicao = %s, ativo = %s WHERE id = %s",
            (nome_exibicao, _bool_para_int(ativo), conta_id),
        )
    else:
        cursor.execute(
            "INSERT INTO contas (email, nome_exibicao, ativo, data_criacao) VALUES (%s, %s, %s, %s) RETURNING id",
            (email, nome_exibicao, _bool_para_int(ativo), datetime.now().strftime("%d/%m/%Y %H:%M")),
        )
        conta_id = cursor.fetchone()["id"]

    # ---- config_conta (credenciais ML) ----
    if config:
        cursor.execute(
            """INSERT INTO config_conta (conta_id, ml_client_id, ml_client_secret, ml_redirect_uri, ml_seller_id)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT(conta_id) DO UPDATE SET
                 ml_client_id = EXCLUDED.ml_client_id,
                 ml_client_secret = EXCLUDED.ml_client_secret,
                 ml_redirect_uri = EXCLUDED.ml_redirect_uri,
                 ml_seller_id = EXCLUDED.ml_seller_id""",
            (
                conta_id,
                config.get("ML_CLIENT_ID", ""),
                config.get("ML_CLIENT_SECRET", ""),
                config.get("ML_REDIRECT_URI", ""),
                config.get("ML_SELLER_ID", ""),
            ),
        )

        cursor.execute("DELETE FROM tokens_mp WHERE conta_id = %s", (conta_id,))
        ordem = 0
        for chave, valor in config.items():
            if chave.startswith("TOKEN_MP") and valor:
                cursor.execute(
                    "INSERT INTO tokens_mp (conta_id, token, ordem) VALUES (%s, %s, %s)",
                    (conta_id, valor, ordem),
                )
                ordem += 1

    # ---- tokens_ml (OAuth do Mercado Livre) ----
    tokens_ml_path = os.path.join(pasta_conta, "ml_tokens_autorizacao.json")
    if os.path.exists(tokens_ml_path):
        with open(tokens_ml_path, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        cursor.execute(
            """INSERT INTO tokens_ml (conta_id, access_token, refresh_token, expires_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT(conta_id) DO UPDATE SET
                 access_token = EXCLUDED.access_token,
                 refresh_token = EXCLUDED.refresh_token,
                 expires_at = EXCLUDED.expires_at""",
            (
                conta_id,
                tokens.get("access_token", ""),
                tokens.get("refresh_token", ""),
                str(tokens.get("expires_in", "")),
            ),
        )

    return conta_id


def migrar_vendas(cursor, pasta_conta, conta_id, email):
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
            
            # Tratamento para campos numéricos/valores
            if campo == "valor":
                if valor is None or str(valor).strip() == "":
                    valor = None
                else:
                    try:
                        valor = float(str(valor).replace(",", "."))
                    except ValueError:
                        valor = None
            elif campo in CAMPOS_BOOLEANOS:
                valor = _bool_para_int(valor)
            elif valor == "":
                valor = None

            valores[campo] = valor

        colunas = ", ".join(["conta_id", "order_id"] + CAMPOS_VENDA)
        placeholders = ", ".join(["%s"] * (2 + len(CAMPOS_VENDA)))
        atualizacoes = ", ".join([f"{c} = EXCLUDED.{c}" for c in CAMPOS_VENDA])

        cursor.execute(
            f"""INSERT INTO vendas ({colunas}) VALUES ({placeholders})
                ON CONFLICT(conta_id, order_id) DO UPDATE SET {atualizacoes}""",
            [conta_id, order_id] + [valores[c] for c in CAMPOS_VENDA],
        )
        total += 1

    print(f"  · {total} venda(s) migrada(s) para {email}")
    return total


def migrar_boletos_excel(cursor, pasta_conta, conta_id, email):
    caminho_excel = os.path.join(pasta_conta, "registros_pedidos.xlsx")
    if not os.path.exists(caminho_excel):
        return 0

    try:
        df = pd.read_excel(caminho_excel)
    except Exception as e:
        print(f"  ! Erro ao ler {caminho_excel}: {e}")
        return 0

    cursor.execute("DELETE FROM boletos_disponiveis WHERE conta_id = %s", (conta_id,))

    total = 0
    for _, row in df.iterrows():
        usado = str(row.get("Boleto Usado", "False")).strip().upper() == "TRUE"
        cursor.execute(
            "INSERT INTO boletos_disponiveis (conta_id, codigo, id_payment, horario, usado) VALUES (%s, %s, %s, %s, %s)",
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


def migrar_tokens_reembolso_raiz(cursor, caminho_projeto_antigo):
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

    cursor.execute("DELETE FROM tokens_reembolso_mp")
    for ordem, token in enumerate(tokens):
        cursor.execute(
            "INSERT INTO tokens_reembolso_mp (token, ordem, ativo) VALUES (%s, %s, 1)",
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

    # Conexão direta passando os parâmetros explícitos
    conn = psycopg2.connect(
        dbname="railway",
        user="postgres",
        password="dRKxNHGNdoXLlsaTRPKgRQwBaDkGcpEu",
        host="metro.proxy.rlwy.net",
        port=44195
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Criar as tabelas caso ainda não existam no PostgreSQL
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contas (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            nome_exibicao VARCHAR(255),
            ativo INT DEFAULT 1,
            data_criacao VARCHAR(50)
        );
        CREATE TABLE IF NOT EXISTS config_conta (
            id SERIAL PRIMARY KEY,
            conta_id INT UNIQUE REFERENCES contas(id) ON DELETE CASCADE,
            ml_client_id VARCHAR(255),
            ml_client_secret VARCHAR(255),
            ml_redirect_uri VARCHAR(255),
            ml_seller_id VARCHAR(255)
        );
        CREATE TABLE IF NOT EXISTS tokens_mp (
            id SERIAL PRIMARY KEY,
            conta_id INT REFERENCES contas(id) ON DELETE CASCADE,
            token TEXT,
            ordem INT DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tokens_ml (
            id SERIAL PRIMARY KEY,
            conta_id INT UNIQUE REFERENCES contas(id) ON DELETE CASCADE,
            access_token TEXT,
            refresh_token TEXT,
            expires_at VARCHAR(100)
        );
        CREATE TABLE IF NOT EXISTS vendas (
            id SERIAL PRIMARY KEY,
            conta_id INT REFERENCES contas(id) ON DELETE CASCADE,
            order_id VARCHAR(100) NOT NULL,
            buyer_id VARCHAR(100),
            produto TEXT,
            valor NUMERIC(10, 2),
            cor_produto VARCHAR(100),
            solicitado INT DEFAULT 0,
            data_solicitacao VARCHAR(50),
            data_solicitacao_inicial VARCHAR(50),
            numero_extraido INT DEFAULT 0,
            zap_extraido VARCHAR(50),
            contatado_wa INT DEFAULT 0,
            rastreio_enviado INT DEFAULT 0,
            data_rastreio VARCHAR(50),
            codigo_rastreio VARCHAR(100),
            boleto_enviado INT DEFAULT 0,
            data_boleto VARCHAR(50),
            codigo_boleto TEXT,
            id_payment VARCHAR(100),
            horario_boleto VARCHAR(50),
            boleto_pago INT DEFAULT 0,
            data_boleto_pago VARCHAR(50),
            boleto_pago_agradecimento INT DEFAULT 0,
            boleto_vencido INT DEFAULT 0,
            boleto_autorizado_msg INT DEFAULT 0,
            cliente_autorizou INT DEFAULT 0,
            cliente_autorizou_via_ia INT DEFAULT 0,
            cobrado_dobro INT DEFAULT 0,
            boleto_pago_dobro INT DEFAULT 0,
            id_payment_dobro VARCHAR(100),
            rembolsado INT DEFAULT 0,
            data_rembolso VARCHAR(50),
            encerrada INT DEFAULT 0,
            cobranca_nao_pago_enviada INT DEFAULT 0,
            UNIQUE(conta_id, order_id)
        );
        CREATE TABLE IF NOT EXISTS boletos_disponiveis (
            id SERIAL PRIMARY KEY,
            conta_id INT REFERENCES contas(id) ON DELETE CASCADE,
            codigo TEXT,
            id_payment VARCHAR(100),
            horario VARCHAR(50),
            usado INT DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tokens_reembolso_mp (
            id SERIAL PRIMARY KEY,
            token TEXT,
            ordem INT DEFAULT 0,
            ativo INT DEFAULT 1
        );
    """)
    conn.commit()

    print(f"Lendo contas em: {accounts_dir}\n")

    total_contas = 0
    total_vendas = 0
    total_boletos = 0

    for nome_pasta in sorted(os.listdir(accounts_dir)):
        pasta_conta = os.path.join(accounts_dir, nome_pasta)
        if not os.path.isdir(pasta_conta):
            continue

        email = nome_pasta
        print(f"[{email}]")

        conta_id = migrar_conta(cursor, pasta_conta, email)
        total_vendas += migrar_vendas(cursor, pasta_conta, conta_id, email)
        total_boletos += migrar_boletos_excel(cursor, pasta_conta, conta_id, email)
        total_contas += 1
        print()

    migrar_tokens_reembolso_raiz(cursor, caminho_projeto_antigo)

    conn.commit()
    cursor.close()
    conn.close()

    print("=" * 60)
    print(f"Migração concluída: {total_contas} conta(s), {total_vendas} venda(s), {total_boletos} boleto(s).")
    print("=" * 60)


if __name__ == "__main__":
    main()