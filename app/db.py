"""
Camada de acesso ao MongoDB Atlas.

É o MESMO banco usado pelo sistema desktop (main.py). Regras:
- Coleção `vendas` (pedidos) segue o contrato do desktop:
      _id      = "<conta>|<order_id>"
      conta    = e-mail da conta (mesmo nome de pasta usado pelo desktop)
      order_id = id do pedido no Mercado Livre (string)
      dados    = estado do pedido (dicionário livre, nomes de campo do desktop)
- Gravações são PARCIAIS (por campo). Nunca sobrescrever a conta inteira, porque
  o desktop pode estar gravando ao mesmo tempo.
- A web nunca apaga pedidos.
- Não inserir dados de exemplo: este banco é de produção.

Configuração (.env):
    MONGODB_URI=mongodb+srv://usuario:senha@cluster.xxxx.mongodb.net/
    MONGODB_DB=coletor_pro        (opcional, padrão coletor_pro)
"""
import os
import threading
from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient

from app.crypto import cifrar, decifrar
from pymongo.errors import DuplicateKeyError

COLECAO_VENDAS = "vendas"
COLECAO_CONTAS = "contas"
COLECAO_CONFIG = "config_conta"
COLECAO_TOKENS = "tokens_ml"
COLECAO_BOLETOS = "boletos_disponiveis"
COLECAO_AGENDAMENTOS = "agendamentos"
COLECAO_EXECUCOES = "agendamento_execucoes"
COLECAO_HISTORICO = "historico_execucao"
COLECAO_LOGS = "logs"
COLECAO_USUARIOS = "usuarios"
COLECAO_TOKENS_MP = "tokens_mp"
COLECAO_TOKENS_REEMBOLSO = "tokens_reembolso_mp"
COLECAO_IA = "ia_scripts"
CAMPOS_SCRIPT_IA = ("script_reclamacao", "script_comum", "script_question")
CAMPOS_SENSIVEIS_CONFIG = ("ml_client_secret",)
CAMPOS_SENSIVEIS_TOKENS_ML = ("access_token", "refresh_token")


def _decifrar_campos(doc, campos):
    for campo in campos:
        if campo in doc:
            doc[campo] = decifrar(doc[campo])
    return doc


def _cifrar_campos(campos, nomes):
    out = dict(campos)
    for nome in nomes:
        if nome in out:
            out[nome] = cifrar(out[nome])
    return out

_lock = threading.Lock()
_client = None
_db = None


def get_db():
    """Devolve o banco (cria a conexão na primeira chamada).
    Nunca loga a URI: ela contém a senha."""
    global _client, _db
    with _lock:
        if _db is None:
            uri = os.environ.get("MONGODB_URI", "").strip()
            if not uri:
                raise RuntimeError("MONGODB_URI não configurada no arquivo .env")
            nome = os.environ.get("MONGODB_DB", "coletor_pro").strip() or "coletor_pro"
            _client = MongoClient(uri, serverSelectionTimeoutMS=10000)
            _db = _client[nome]
    return _db


def colecao(nome):
    return get_db()[nome]


def init_indices():
    """Cria índices necessários. Idempotente. Não altera documentos de dados."""
    colecao(COLECAO_VENDAS).create_index("conta")
    colecao(COLECAO_CONTAS).create_index("email", unique=True, sparse=True)
    colecao(COLECAO_USUARIOS).create_index("usuario", unique=True)
    colecao(COLECAO_BOLETOS).create_index([("conta", 1), ("usado", 1)])
    colecao(COLECAO_AGENDAMENTOS).create_index("conta")
    colecao(COLECAO_EXECUCOES).create_index(
        [("agendamento_id", 1), ("horario", 1), ("data", 1)], unique=True
    )
    colecao(COLECAO_LOGS).create_index([("conta", 1), ("_id", 1)])
    colecao(COLECAO_HISTORICO).create_index("agendamento_id")


def _validar_campos(campos):
    """Nomes de campo do MongoDB não podem conter '.' nem começar com '$'."""
    for nome in campos:
        if not isinstance(nome, str) or not nome or "." in nome or nome.startswith("$"):
            raise ValueError(f"Nome de campo inválido: {nome!r}")


def agora_texto():
    """Mesmo formato de data usado pelo desktop."""
    return datetime.now().strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# CONTAS
# ---------------------------------------------------------------------------
def listar_contas():
    """Contas cadastradas na web + contas que já têm pedidos (vindas do desktop).
    Não grava nada."""
    cadastradas = {d["_id"]: d for d in colecao(COLECAO_CONTAS).find({"ativo": True})}
    for email in colecao(COLECAO_VENDAS).distinct("conta"):
        cadastradas.setdefault(email, {"_id": email, "nome_exibicao": email, "ativo": True})

    contas = []
    for chave in sorted(cadastradas):
        c = cadastradas[chave]
        contas.append({
            "id": chave,
            "email": c.get("email", chave),
            "nome_exibicao": c.get("nome_exibicao") or chave,
            "ativo": True,
        })
    return contas


def conta_existe(email):
    if colecao(COLECAO_CONTAS).find_one({"_id": email}, {"_id": 1}):
        return True
    return colecao(COLECAO_VENDAS).find_one({"conta": email}, {"_id": 1}) is not None


def criar_conta(email, nome_exibicao):
    """Cria a conta. Lança DuplicateKeyError se já existir (quem chama checa antes)."""
    colecao(COLECAO_CONTAS).insert_one({
        "_id": email,
        "email": email,
        "nome_exibicao": nome_exibicao,
        "ativo": True,
        "data_criacao": agora_texto(),
    })


# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DA CONTA (credenciais ML, nome da loja, etc.)
# ---------------------------------------------------------------------------
def obter_config_conta(conta):
    doc = colecao(COLECAO_CONFIG).find_one({"_id": conta}) or {}
    doc.pop("_id", None)
    return _decifrar_campos(doc, CAMPOS_SENSIVEIS_CONFIG)


def salvar_config_conta(conta, campos):
    """Altera só os campos informados (preserva os demais)."""
    if not campos:
        return
    _validar_campos(campos)
    campos = _cifrar_campos(campos, CAMPOS_SENSIVEIS_CONFIG)
    colecao(COLECAO_CONFIG).update_one({"_id": conta}, {"$set": campos}, upsert=True)


# ---------------------------------------------------------------------------
# TOKENS DO MERCADO LIVRE
# ---------------------------------------------------------------------------
def obter_tokens_ml(conta):
    doc = colecao(COLECAO_TOKENS).find_one({"_id": conta}) or {}
    doc.pop("_id", None)
    return _decifrar_campos(doc, CAMPOS_SENSIVEIS_TOKENS_ML)


def salvar_tokens_ml(conta, access_token, refresh_token, expires_at):
    colecao(COLECAO_TOKENS).update_one(
        {"_id": conta},
        {"$set": {
            "access_token": cifrar(access_token),
            "refresh_token": cifrar(refresh_token),
            "expires_at": expires_at,
        }},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# VENDAS (pedidos)
# ---------------------------------------------------------------------------
def chave_pedido(conta, order_id):
    return f"{conta}|{str(order_id)}"


def listar_pedidos(conta):
    """Retorna {order_id: dados} de todos os pedidos da conta."""
    cursor = colecao(COLECAO_VENDAS).find(
        {"conta": conta}, {"_id": 0, "order_id": 1, "dados": 1}
    )
    return {doc["order_id"]: doc.get("dados", {}) for doc in cursor}


def obter_pedido(conta, order_id):
    """Retorna o dicionário `dados` do pedido, ou None se não existir."""
    doc = colecao(COLECAO_VENDAS).find_one(
        {"_id": chave_pedido(conta, order_id)}, {"_id": 0, "dados": 1}
    )
    return doc.get("dados", {}) if doc else None


def atualizar_campos_pedido(conta, order_id, campos):
    """Altera apenas os campos informados. Cria o pedido se não existir."""
    if not campos:
        return
    _validar_campos(campos)
    oid = str(order_id)
    sets = {f"dados.{nome}": valor for nome, valor in campos.items()}
    colecao(COLECAO_VENDAS).update_one(
        {"_id": chave_pedido(conta, oid)},
        {"$set": {**sets, "conta": conta, "order_id": oid}},
        upsert=True,
    )


def contar_pedidos_com(conta, filtro_dados):
    """Conta pedidos da conta cujos campos de `dados` batem com o filtro.
    Ex.: {"boleto_vencido": True}. Chaves são prefixadas com 'dados.' aqui."""
    consulta = {"conta": conta}
    for nome, valor in filtro_dados.items():
        consulta[f"dados.{nome}"] = valor
    return colecao(COLECAO_VENDAS).count_documents(consulta)


def contar_pedidos_regex(conta, campo, prefixo):
    """Conta pedidos cujo campo `dados.<campo>` começa com `prefixo` (ex.: data 'dd/mm/aaaa')."""
    return colecao(COLECAO_VENDAS).count_documents({
        "conta": conta,
        f"dados.{campo}": {"$regex": f"^{prefixo}"},
    })


# ---------------------------------------------------------------------------
# BOLETOS DISPONÍVEIS
# ---------------------------------------------------------------------------
def provedor_boleto(valor):
    """Normaliza o provedor de um boleto: 'ASAAS', 'MP' ou '' (vazio = Mercado Pago)."""
    p = str(valor or "").strip().lower()
    if "asaas" in p:
        return "ASAAS"
    if "mercado" in p or p == "mp":
        return "MP"
    return ""


def buscar_proximo_boleto(conta, provedor=None):
    """Próximo boleto não usado. `provedor` ('MP' ou 'ASAAS') restringe ao mesmo
    provedor da taxa da venda, igual ao desktop. Vazio/None = qualquer."""
    cursor = colecao(COLECAO_BOLETOS).find({"conta": conta, "usado": False}).sort("_id", 1)
    for doc in cursor:
        prov = provedor_boleto(doc.get("provedor"))
        if provedor == "ASAAS" and prov != "ASAAS":
            continue
        if provedor == "MP" and prov not in ("MP", ""):
            continue
        return {
            "id": str(doc["_id"]),
            "codigo": doc.get("codigo"),
            "id_payment": doc.get("id_payment"),
            "horario": doc.get("horario"),
            "provedor": prov,
        }
    return None


def marcar_boleto_usado(boleto_id):
    colecao(COLECAO_BOLETOS).update_one(
        {"_id": ObjectId(boleto_id)}, {"$set": {"usado": True}}
    )


def contar_boletos_disponiveis(conta):
    return colecao(COLECAO_BOLETOS).count_documents({"conta": conta, "usado": False})


# ---------------------------------------------------------------------------
# AGENDAMENTOS (controle de execução usado pelo worker)
# ---------------------------------------------------------------------------
def contar_agendamentos_ativos(conta):
    return colecao(COLECAO_AGENDAMENTOS).count_documents({"conta": conta, "ativo": True})


def reservar_execucao(agendamento_id, horario, data):
    """Registra que um agendamento vai rodar neste horário/dia.
    Devolve False se já foi reservado. Garante uma única execução por disparo."""
    try:
        colecao(COLECAO_EXECUCOES).insert_one({
            "agendamento_id": str(agendamento_id),
            "horario": horario,
            "data": data,
            "criado_em": agora_texto(),
        })
    except DuplicateKeyError:
        return False
    return True


def _id_valido(valor):
    try:
        return ObjectId(valor)
    except (InvalidId, TypeError):
        return None


# ---------------------------------------------------------------------------
# TOKENS MERCADO PAGO (por conta)
# ---------------------------------------------------------------------------
def listar_tokens_mp(conta):
    cursor = colecao(COLECAO_TOKENS_MP).find({"conta": conta}).sort("ordem", 1)
    return [
        {"id": str(d["_id"]), "token": decifrar(d.get("token", "")), "ordem": d.get("ordem", 0)}
        for d in cursor if d.get("token")
    ]


def obter_tokens_mp(conta):
    return [t["token"] for t in listar_tokens_mp(conta)]


def adicionar_token_mp(conta, token):
    token = (token or "").strip()
    if not token:
        return
    ultimo = colecao(COLECAO_TOKENS_MP).find_one({"conta": conta}, sort=[("ordem", -1)])
    ordem = (ultimo.get("ordem", 0) + 1) if ultimo else 0
    colecao(COLECAO_TOKENS_MP).insert_one({"conta": conta, "token": cifrar(token), "ordem": ordem})


def remover_token_mp(token_id):
    oid = _id_valido(token_id)
    if oid:
        colecao(COLECAO_TOKENS_MP).delete_one({"_id": oid})


# ---------------------------------------------------------------------------
# TOKENS DE REEMBOLSO MERCADO PAGO (COMPARTILHADOS entre todas as contas)
# ---------------------------------------------------------------------------
def listar_tokens_reembolso(somente_ativos=False):
    filtro = {"ativo": True} if somente_ativos else {}
    cursor = colecao(COLECAO_TOKENS_REEMBOLSO).find(filtro).sort("ordem", 1)
    return [
        {
            "id": str(d["_id"]),
            "token": decifrar(d.get("token", "")),
            "ordem": d.get("ordem", 0),
            "ativo": bool(d.get("ativo", True)),
        }
        for d in cursor if d.get("token")
    ]


def obter_tokens_reembolso():
    """Tokens de reembolso ATIVOS (usados de fato no reembolso)."""
    return [t["token"] for t in listar_tokens_reembolso(somente_ativos=True)]


def adicionar_token_reembolso(token):
    token = (token or "").strip()
    if not token:
        return
    ultimo = colecao(COLECAO_TOKENS_REEMBOLSO).find_one({}, sort=[("ordem", -1)])
    ordem = (ultimo.get("ordem", 0) + 1) if ultimo else 0
    colecao(COLECAO_TOKENS_REEMBOLSO).insert_one({"token": cifrar(token), "ordem": ordem, "ativo": True})


def remover_token_reembolso(token_id):
    oid = _id_valido(token_id)
    if oid:
        colecao(COLECAO_TOKENS_REEMBOLSO).delete_one({"_id": oid})


def alternar_token_reembolso(token_id):
    oid = _id_valido(token_id)
    if not oid:
        return
    doc = colecao(COLECAO_TOKENS_REEMBOLSO).find_one({"_id": oid}, {"ativo": 1})
    if doc:
        colecao(COLECAO_TOKENS_REEMBOLSO).update_one(
            {"_id": oid}, {"$set": {"ativo": not bool(doc.get("ativo", True))}}
        )


# ---------------------------------------------------------------------------
# SCRIPTS DA IA (por conta)
# ---------------------------------------------------------------------------
# Scripts da IA são GLOBAIS: valem para todas as contas. O argumento `conta`
# é mantido só por compatibilidade com as chamadas existentes e é ignorado.
CHAVE_SCRIPTS_GLOBAIS = "global"


def obter_script_ia(conta=None, campo="script_question"):
    if campo not in CAMPOS_SCRIPT_IA:
        return None
    doc = colecao(COLECAO_IA).find_one({"_id": CHAVE_SCRIPTS_GLOBAIS}, {campo: 1})
    return doc.get(campo) if doc else None


def salvar_script_ia(conta, campo, texto):
    if campo not in CAMPOS_SCRIPT_IA:
        raise ValueError(f"Campo de script inválido: {campo}")
    colecao(COLECAO_IA).update_one(
        {"_id": CHAVE_SCRIPTS_GLOBAIS}, {"$set": {campo: texto}}, upsert=True
    )


# ---------------------------------------------------------------------------
# REEMBOLSO: pedidos pagos que ainda não foram reembolsados
# ---------------------------------------------------------------------------
def listar_vendas_reembolsaveis(conta):
    cursor = colecao(COLECAO_VENDAS).find(
        {
            "conta": conta,
            "dados.boleto_pago": True,
            "dados.rembolsado": {"$ne": True},
            "dados.id_payment": {"$nin": [None, ""]},
        },
        {"_id": 0, "order_id": 1, "dados": 1},
    ).sort("order_id", -1)
    return [
        {
            "order_id": d["order_id"],
            "produto": d.get("dados", {}).get("produto"),
            "valor": d.get("dados", {}).get("valor"),
            "id_payment": d.get("dados", {}).get("id_payment"),
            "data_boleto_pago": d.get("dados", {}).get("data_boleto_pago"),
        }
        for d in cursor
    ]


# ---------------------------------------------------------------------------
# AGENDAMENTOS (cadastro e histórico)
# ---------------------------------------------------------------------------
def _agendamento_view(d):
    horarios = d.get("horarios") or []
    return {
        "id": str(d["_id"]),
        "nome": d.get("nome", ""),
        "conta": d.get("conta"),
        "conta_email": d.get("conta"),
        "tipo": d.get("tipo", "diaria"),
        "acao": d.get("acao"),
        "horarios": ", ".join(horarios) if isinstance(horarios, list) else str(horarios),
        "data": d.get("data"),
        "ativo": bool(d.get("ativo", True)),
    }


def listar_agendamentos():
    return [_agendamento_view(d) for d in colecao(COLECAO_AGENDAMENTOS).find().sort("_id", -1)]


def obter_agendamento_bruto(agendamento_id):
    oid = _id_valido(agendamento_id)
    return colecao(COLECAO_AGENDAMENTOS).find_one({"_id": oid}) if oid else None


def criar_agendamento(nome, conta, tipo, acao, horarios, data, ativo, parametros=None):
    colecao(COLECAO_AGENDAMENTOS).insert_one({
        "nome": nome,
        "conta": conta,
        "tipo": tipo,
        "acao": acao,
        "horarios": horarios,
        "data": data,
        "ativo": bool(ativo),
        "parametros": parametros or {},
        "criado_em": agora_texto(),
    })


def alternar_agendamento(agendamento_id):
    doc = obter_agendamento_bruto(agendamento_id)
    if doc:
        colecao(COLECAO_AGENDAMENTOS).update_one(
            {"_id": doc["_id"]}, {"$set": {"ativo": not bool(doc.get("ativo", True))}}
        )


def remover_agendamento(agendamento_id):
    oid = _id_valido(agendamento_id)
    if oid:
        colecao(COLECAO_AGENDAMENTOS).delete_one({"_id": oid})


def registrar_historico(agendamento_id, tarefa_nome, acao, status, mensagem):
    colecao(COLECAO_HISTORICO).insert_one({
        "agendamento_id": str(agendamento_id) if agendamento_id else None,
        "tarefa_nome": tarefa_nome,
        "acao": acao,
        "status": status,
        "mensagem": mensagem,
        "data_hora": agora_texto(),
    })


def listar_historico(limite=30):
    cursor = colecao(COLECAO_HISTORICO).find().sort("_id", -1).limit(limite)
    return [{**{k: v for k, v in d.items() if k != "_id"}} for d in cursor]


def marcar_pedido_encerrado(conta, order_id):
    """Marca `dados.encerrada = True` somente se o pedido já existir.
    Diferente de atualizar_campos_pedido, NÃO cria o documento.
    Retorna True se o pedido existia."""
    resultado = colecao(COLECAO_VENDAS).update_one(
        {"_id": chave_pedido(conta, order_id)},
        {"$set": {"dados.encerrada": True}},
    )
    return resultado.matched_count == 1


# ---------------------------------------------------------------------------
# USUÁRIOS DO SISTEMA (login). Cadastrados manualmente no banco.
# Documento: {usuario: "nome", senha_hash: "<hash>", ativo: true}
# ---------------------------------------------------------------------------
def obter_usuario(usuario):
    if not usuario:
        return None
    return colecao(COLECAO_USUARIOS).find_one({"usuario": usuario, "ativo": True}, {"_id": 0})
