"""
Camada de acesso ao banco SQLite, usando sqlite3 puro (biblioteca padrão do Python).

Por que sqlite3 puro em vez de um ORM: zero dependências extras, fácil de
entender linha a linha, e para o volume de dados desse sistema (uma loja/
pequena operação) não há ganho real em usar SQLAlchemy. Se o projeto crescer
muito, migrar para SQLAlchemy depois é tranquilo — o schema já está pronto.
"""
import os
import sqlite3
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # pasta appweb/
DB_PATH = os.path.join(BASE_DIR, "database.db")


def get_connection():
    """Abre uma conexão nova. Cada request do Flask deve abrir e fechar a sua."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acessar colunas por nome: row["email"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    nome_exibicao TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    data_criacao TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_conta (
    conta_id INTEGER PRIMARY KEY REFERENCES contas(id) ON DELETE CASCADE,
    ml_client_id TEXT,
    ml_client_secret TEXT,
    ml_redirect_uri TEXT,
    ml_seller_id TEXT
);

CREATE TABLE IF NOT EXISTS tokens_ml (
    conta_id INTEGER PRIMARY KEY REFERENCES contas(id) ON DELETE CASCADE,
    access_token TEXT,
    refresh_token TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS tokens_mp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
    token TEXT NOT NULL,
    ordem INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tokens_reembolso_mp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    ordem INTEGER DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    buyer_id TEXT,
    produto TEXT,
    valor TEXT,
    cor_produto TEXT,

    solicitado INTEGER DEFAULT 0,
    data_solicitacao TEXT,
    data_solicitacao_inicial TEXT,
    tentativa_ INTEGER DEFAULT 0,

    numero_extraido INTEGER DEFAULT 0,
    zap_extraido TEXT,
    contatado_wa INTEGER DEFAULT 0,

    rastreio_enviado INTEGER DEFAULT 0,
    data_rastreio TEXT,
    codigo_rastreio TEXT,

    boleto_enviado INTEGER DEFAULT 0,
    data_boleto TEXT,
    codigo_boleto TEXT,
    id_payment TEXT,
    horario_boleto TEXT,

    boleto_pago INTEGER DEFAULT 0,
    data_boleto_pago TEXT,
    boleto_pago_agradecimento INTEGER DEFAULT 0,
    boleto_vencido INTEGER DEFAULT 0,

    boleto_autorizado_msg INTEGER DEFAULT 0,
    cliente_autorizou INTEGER DEFAULT 0,
    cliente_autorizou_via_ia INTEGER DEFAULT 0,

    cobrado_dobro INTEGER DEFAULT 0,
    boleto_pago_dobro INTEGER DEFAULT 0,
    id_payment_dobro TEXT,

    rembolsado INTEGER DEFAULT 0,
    data_rembolso TEXT,

    encerrada INTEGER DEFAULT 0,
    cobranca_nao_pago_enviada INTEGER DEFAULT 0,

    UNIQUE(conta_id, order_id)
);

CREATE TABLE IF NOT EXISTS boletos_disponiveis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
    codigo TEXT NOT NULL,
    id_payment TEXT,
    horario TEXT,
    usado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agendamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,               -- 'diaria' ou 'unica'
    acao TEXT NOT NULL,
    horarios TEXT NOT NULL,           -- JSON: ["08:00", "14:00"]
    data TEXT,                        -- só para tipo 'unica'
    ativo INTEGER NOT NULL DEFAULT 1,
    intervalo_minutos INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS historico_execucao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agendamento_id INTEGER REFERENCES agendamentos(id) ON DELETE SET NULL,
    tarefa_nome TEXT,
    acao TEXT,
    status TEXT,                      -- SUCESSO / ERRO
    mensagem TEXT,
    data_hora TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER REFERENCES contas(id) ON DELETE CASCADE,
    nivel TEXT NOT NULL,              -- info / sucesso / aviso / erro
    mensagem TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whatsapp_instancias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT,
    instancia TEXT,
    token TEXT,
    porta TEXT,
    limite INTEGER DEFAULT 200,
    contador_enviados INTEGER DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ia_scripts (
    conta_id INTEGER PRIMARY KEY REFERENCES contas(id) ON DELETE CASCADE,
    script_reclamacao TEXT,
    script_comum TEXT,
    script_question TEXT
);
"""


def init_db():
    """Cria o arquivo do banco e todas as tabelas, se ainda não existirem.
    Chamado uma vez na inicialização do app (ver app/__init__.py)."""
    conn = get_connection()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# SEED — dados de exemplo, só para o protótipo ter algo pra mostrar
# ---------------------------------------------------------------------------
def seed_dados_exemplo():
    conn = get_connection()
    ja_tem_dados = conn.execute("SELECT COUNT(*) AS n FROM contas").fetchone()["n"] > 0
    if ja_tem_dados:
        conn.close()
        return

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    hoje = date.today().strftime("%d/%m/%Y")

    cur = conn.execute(
        "INSERT INTO contas (email, nome_exibicao, ativo, data_criacao) VALUES (?, ?, 1, ?)",
        ("loja.exemplo@gmail.com", "Loja Exemplo", agora),
    )
    conta_id = cur.lastrowid

    conn.execute(
        "INSERT INTO contas (email, nome_exibicao, ativo, data_criacao) VALUES (?, ?, 1, ?)",
        ("outra.loja@gmail.com", "Outra Loja", agora),
    )

    vendas_exemplo = [
        # order_id, produto, valor, boleto_enviado, boleto_pago, data_boleto_pago, boleto_vencido, boleto_autorizado_msg, cliente_autorizou
        ("2000111111", "Painel de LED 3D", "R$ 189,90", 1, 1, hoje, 0, 1, 1),
        ("2000111112", "Luminária Geométrica", "R$ 129,90", 1, 1, hoje, 0, 1, 1),
        ("2000111113", "Quadro Decorativo", "R$ 99,90", 1, 0, None, 0, 1, 0),
        ("2000111114", "Espelho Decorativo", "R$ 159,90", 1, 0, None, 1, 1, 0),
        ("2000111115", "Vaso Cerâmica", "R$ 79,90", 0, 0, None, 0, 1, 0),
        ("2000111116", "Suporte de TV", "R$ 219,90", 0, 0, None, 0, 0, 0),
    ]
    for order_id, produto, valor, benv, bpago, dpago, bvenc, bautor, cliaut in vendas_exemplo:
        conn.execute(
            """INSERT INTO vendas
               (conta_id, order_id, produto, valor, boleto_enviado, boleto_pago,
                data_boleto_pago, boleto_vencido, boleto_autorizado_msg, cliente_autorizou,
                data_solicitacao_inicial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (conta_id, order_id, produto, valor, benv, bpago, dpago, bvenc, bautor, cliaut, agora),
        )

    conn.execute(
        """INSERT INTO agendamentos (nome, conta_id, tipo, acao, horarios, ativo, intervalo_minutos)
           VALUES (?, ?, 'diaria', 'boleto', '["08:00", "14:00"]', 1, 0)""",
        ("Envio de boletos da manhã", conta_id),
    )
    conn.execute(
        """INSERT INTO agendamentos (nome, conta_id, tipo, acao, horarios, ativo, intervalo_minutos)
           VALUES (?, ?, 'diaria', 'rastreio', '["09:00"]', 1, 0)""",
        ("Rastreios diários", conta_id),
    )

    logs_exemplo = [
        ("info", "Buscando offset 0..."),
        ("sucesso", "Ordem 2000111111: Boleto enviado com sucesso!"),
        ("aviso", "Ordem 2000111113 ignorada: cliente não autorizou com '1'."),
        ("info", "Processamento da ordem 2000111114 concluído. Próxima ordem..."),
        ("erro", "Falha ao enviar código do boleto para a ordem 2000111116."),
        ("sucesso", "Fim da execução. Novas solicitações enviadas: 12"),
    ]
    for nivel, msg in logs_exemplo:
        conn.execute(
            "INSERT INTO logs (conta_id, nivel, mensagem, timestamp) VALUES (?, ?, ?, ?)",
            (conta_id, nivel, msg, agora),
        )

    conn.commit()
    conn.close()
