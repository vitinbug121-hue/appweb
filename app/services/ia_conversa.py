"""
Etapa 7 — IA unificada de chat e reclamações (portada de
`_responder_com_ia_unificada`, `responder_chat_comum_com_ia`,
`responder_reclamacao_com_ia` e `_montar_parametros_dinamicos` do desktop).

Fluxo por pedido:
  1. Monta a conversa (chat + reclamações ligadas ao pedido).
  2. Pega as mensagens do cliente após a última resposta da loja.
  3. Bloqueia: pedido PIX, cliente já cobrado (boleto_autorizado_msg) ou pedido não solicitado.
  4. Evita repetir resposta (hash da sequência em ultima_ia_chave).
  5. Classifica se precisa responder (TRUE/FALSE). Se não, só registra o hash.
  6. Gera a resposta com o script comum e os PARAMETROS do pedido (até 2 tentativas).
  7. Envia (chat ou reclamação) e grava ultima_ia_chave/resposta/data.

Reclamação com o texto padrão "Tive um problema com a compra e preciso de ajuda":
resposta fixa, sem IA (regra de negócio do desktop).

Texto fixo copiado do desktop (inclui o recuo literal das linhas). Não reescrever.
"""
import hashlib
import re
import time
from datetime import datetime

from app.db import agora_texto, atualizar_campos_pedido, listar_pedidos, obter_config_conta, obter_script_ia
from app.services import groq_ia, mercadolivre
from app.services.controle import ParadaSolicitada
from app.services.logger import log_evento

PAUSA_ENTRE_PEDIDOS = 0.5
GATILHO_RECLAMACAO_PADRAO = "Tive um problema com a compra e preciso de ajuda"

RESPOSTA_RECLAMACAO_PADRAO = 'Olá! Entendo perfeitamente e estou aqui para ajudar você a resolver isso da melhor forma.\n\n            Como o seu pedido é importado direto da fábrica, nos raros casos em que a Receita Federal aplica alguma taxa, ficando entre R$ 220 e R$ 300.\n\n            Para que você não saia prejudicado, já garantimos para você a montagem totalmente gratuita do seu móvel, além de brindes especiais: 3 vasos de cerâmica decorativos\n\n            Conte comigo para acompanhar todo o processo até a entrega na sua casa.\n\n            Atenciosamente,\n            {nome_loja}'


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def mensagens_cliente_apos_ultima_resposta(conversa):
    """Textos do cliente depois da última mensagem da loja (ordem cronológica)."""
    ordenada = sorted(conversa, key=lambda m: str(m.get("data") or ""))
    ultima = None
    for idx, m in enumerate(ordenada):
        if m.get("is_seller"):
            ultima = idx
    recentes = ordenada[ultima + 1:] if ultima is not None else ordenada
    return [str(m.get("texto") or "").strip() for m in recentes
            if str(m.get("texto") or "").strip() and not m.get("is_seller")]


def _bool(valor):
    return "true" if bool(valor) else "false"


def montar_parametros(dados, tem_reclamacao):
    """Bloco PARAMETROS da etapa do pedido. Formato idêntico ao desktop.
    Observação: o desktop envia `metodo_taxa` como true/false (não o valor).
    Mantido por fidelidade ao prompt; ver nota na resposta da etapa."""
    tipo = str(dados.get("tipo_rastreio") or "").strip().lower()
    if tipo not in ("aliexpress", "br"):
        tipo = "nao_informado" if dados.get("rastreio_enviado") else "nenhum"

    metodo = str(dados.get("metodo_taxa") or "").strip().lower()
    if metodo == "pix":
        forma = "pix"
    elif metodo == "boleto":
        forma = "boleto_asaas" if str(dados.get("provedor_taxa") or "").upper() == "ASAAS" else "boleto_mercado_pago"
    else:
        forma = "nao_informada"

    linhas = [
        f"conversa_com_reclamação = {_bool(tem_reclamacao)}.",
        f"solicitado = {_bool(dados.get('solicitado'))}.",
        f"rastreio_enviado = {_bool(dados.get('rastreio_enviado'))}.",
        f"tipo_rastreio = {tipo}.",
        f"boleto_autorizado_msg = {_bool(dados.get('boleto_autorizado_msg'))}.",
        f"cliente_autorizou = {_bool(dados.get('cliente_autorizou'))}.",
        f"boleto_enviado = {_bool(dados.get('boleto_enviado'))}.",
        f"boleto_pago = {_bool(dados.get('boleto_pago'))}.",
        f"metodo_taxa = {_bool(dados.get('metodo_taxa'))}.",
        f"forma_taxa = {forma}.",
    ]
    return "\n        ".join(linhas)


def _chave_sequencia(texto_cliente):
    return hashlib.sha256(texto_cliente.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Conversa completa (chat + reclamações)
# ---------------------------------------------------------------------------
def obter_conversa_completa(conta, order_id, pack_id=None):
    """Retorna (mensagens, claim_ids). Mensagens do chat e das reclamações, em ordem."""
    mensagens = list(mercadolivre.obter_conversa(conta, order_id, pack_id))
    claim_ids = mercadolivre.obter_claim_ids(conta, order_id, pack_id)
    for claim_id in claim_ids:
        mensagens.extend(mercadolivre.obter_mensagens_reclamacao(conta, claim_id))
    mensagens.sort(key=lambda m: str(m.get("data") or ""))
    return mensagens, claim_ids


# ---------------------------------------------------------------------------
# Resposta de um pedido
# ---------------------------------------------------------------------------
def _responder(conta, order_id, buyer_id, conversa, dados, tem_reclamacao, claim_id, nome_loja):
    script = (obter_script_ia(conta, "script_comum") or "").strip()
    if not script:
        log_evento(conta, "erro", "Script da IA (script_comum) não configurado. Resposta cancelada.")
        return "sem_script"

    if str(dados.get("metodo_taxa") or "").lower() == "pix":
        return "bloqueado_pix"
    if dados.get("boleto_autorizado_msg") is True:
        return "bloqueado_cobrado"
    if dados.get("solicitado") is not True:
        return "bloqueado_nao_solicitado"

    mensagens = mensagens_cliente_apos_ultima_resposta(conversa)
    if not mensagens:
        return "sem_novidade"

    texto_cliente = "\n\n".join(f"Cliente: {t}" for t in mensagens)
    chave = _chave_sequencia(texto_cliente)
    if dados.get("ultima_ia_chave") == chave:
        return "ja_respondida"

    # Reclamação padrão: resposta fixa, sem IA
    if tem_reclamacao and GATILHO_RECLAMACAO_PADRAO in texto_cliente:
        resposta = RESPOSTA_RECLAMACAO_PADRAO.format(nome_loja=nome_loja)
    else:
        try:
            precisa = groq_ia.precisa_responder(texto_cliente)
        except ParadaSolicitada:
            raise
        except Exception as e:
            log_evento(conta, "erro", f"Ordem {order_id}: erro ao classificar necessidade de resposta — {e}")
            return "erro_classificador"

        if not precisa:
            atualizar_campos_pedido(conta, order_id, {"ultima_ia_chave": chave})
            log_evento(conta, "info", f"Ordem {order_id}: mensagem do cliente não exige resposta.")
            return "nao_precisa"

        parametros = montar_parametros(dados, tem_reclamacao)
        prompt = f"PARAMETROS:\n        {parametros}\nMensagem do cliente:\n{texto_cliente}"
        try:
            resposta = groq_ia.gerar_resposta_ia(script, prompt)
            if not resposta:
                resposta = groq_ia.gerar_resposta_ia(script, prompt)  # segunda tentativa
        except ParadaSolicitada:
            raise
        except Exception as e:
            log_evento(conta, "erro", f"Ordem {order_id}: erro ao gerar resposta da IA — {e}")
            return "erro_ia"
        resposta = (resposta or "").strip().strip('"')
        if not resposta:
            log_evento(conta, "erro", f"Ordem {order_id}: IA retornou resposta vazia nas duas tentativas.")
            return "vazia"

    if tem_reclamacao:
        ok, detalhe = mercadolivre.enviar_mensagem_reclamacao(conta, claim_id, resposta)
    else:
        ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, resposta)

    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar resposta da IA — {detalhe}")
        return "falha_envio"

    atualizar_campos_pedido(conta, order_id, {
        "ultima_ia_chave": chave,
        "ultima_ia_resposta": resposta,
        "data_ultima_ia": agora_texto(),
    })
    log_evento(conta, "sucesso", f"Ordem {order_id}: resposta da IA enviada{' (reclamação)' if tem_reclamacao else ''}.")
    return "enviada"


def responder_pedido(conta, order_id, dados, nome_loja=None):
    nome = nome_loja or (obter_config_conta(conta).get("nome_loja") or "").strip()
    buyer_id = str(dados.get("buyer_id") or "")
    if not buyer_id:
        return "sem_comprador"

    conversa, claim_ids = obter_conversa_completa(conta, order_id, dados.get("pack_id"))
    claim_id = str(claim_ids[0]) if claim_ids else None
    return _responder(conta, order_id, buyer_id, conversa, dados, bool(claim_id), claim_id, nome)


def _filtrar_candidatos(conta, pedidos, lote=None, excluir_pix=False, somente_nao_taxados=False):
    """Pedidos solicitados que passam pelos filtros da tela. Devolve (candidatos, filtrados)."""
    from app.services import autorizacao
    ids_lote = None
    if lote:
        l = next((x for x in autorizacao.calcular_lotes(conta) if x["numero"] == int(lote)), None)
        if not l:
            raise ValueError(f"Lote {lote} não encontrado.")
        ids_lote = set(l["ids"])

    candidatos, filtrados = [], 0
    for oid in sorted(pedidos):
        d = pedidos[oid]
        if d.get("solicitado") is not True:
            continue
        if ids_lote is not None and str(oid) not in ids_lote:
            filtrados += 1
            continue
        if excluir_pix and (str(d.get("metodo_taxa") or "").lower() == "pix" or d.get("cobrado_via_pix")):
            filtrados += 1
            continue
        if somente_nao_taxados and d.get("boleto_autorizado_msg"):
            filtrados += 1
            continue
        candidatos.append(oid)
    return candidatos, filtrados


def responder_lote(conta, limite=20, lote=None, excluir_pix=False, somente_nao_taxados=False):
    """Executa a IA nos pedidos solicitados que passam pelos filtros da tela."""
    pedidos = listar_pedidos(conta)
    try:
        candidatos, filtrados = _filtrar_candidatos(conta, pedidos, lote, excluir_pix, somente_nao_taxados)
    except ValueError as e:
        return {"erro": str(e)}

    resumo = {"verificados": 0, "enviadas": 0, "nao_precisa": 0, "falhas": 0, "bloqueadas": 0, "filtrados": filtrados}
    chaves = {
        "enviada": "enviadas", "nao_precisa": "nao_precisa",
        "falha_envio": "falhas", "erro_ia": "falhas", "erro_classificador": "falhas", "vazia": "falhas",
    }
    for oid in candidatos:
        if resumo["verificados"] >= limite:
            break
        resumo["verificados"] += 1
        try:
            resultado = responder_pedido(conta, oid, pedidos[oid])
        except ParadaSolicitada:
            raise
        except Exception as e:
            resultado = "erro_ia"
            log_evento(conta, "erro", f"Ordem {oid}: erro inesperado na IA — {e}")
        if resultado in chaves:
            resumo[chaves[resultado]] += 1
        elif resultado.startswith("bloqueado"):
            resumo["bloqueadas"] += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(conta, "sucesso",
               f"IA finalizada. Verificados: {resumo['verificados']} | Enviadas: {resumo['enviadas']} | "
               f"Não precisam de resposta: {resumo['nao_precisa']} | Bloqueadas: {resumo['bloqueadas']} | "
               f"Filtradas: {resumo['filtrados']} | Falhas: {resumo['falhas']}")
    return resumo


def testar(script, texto_cliente, dados, tem_reclamacao=False, nome_loja=""):
    """Simula a resposta da IA para uma mensagem e uma situação de venda. NÃO envia nada."""
    texto_cliente = (texto_cliente or "").strip()
    bloqueios = []
    if str(dados.get("metodo_taxa") or "").lower() == "pix":
        bloqueios.append("Venda com taxa via PIX: a IA não responde.")
    if dados.get("boleto_autorizado_msg"):
        bloqueios.append("Cliente já taxado (autorização enviada): a IA não responde.")
    if dados.get("solicitado") is not True:
        bloqueios.append("Pedido não solicitado: a IA não responde.")

    parametros = montar_parametros(dados, tem_reclamacao)
    prompt = f"PARAMETROS:\n        {parametros}\nMensagem do cliente:\nCliente: {texto_cliente}"
    out = {"bloqueios": bloqueios, "parametros": parametros, "prompt": prompt,
           "precisa": None, "resposta": None, "erro": None}

    if tem_reclamacao and GATILHO_RECLAMACAO_PADRAO in texto_cliente:
        out["precisa"] = True
        out["resposta"] = RESPOSTA_RECLAMACAO_PADRAO.format(nome_loja=nome_loja or "")
        out["motivo"] = "Reclamação padrão: resposta fixa, sem IA."
        return out

    try:
        out["precisa"] = groq_ia.precisa_responder(f"Cliente: {texto_cliente}")
    except Exception as e:
        out["erro"] = f"Classificador falhou: {e}"
        return out
    if not out["precisa"]:
        out["motivo"] = "O classificador entendeu que a mensagem não exige resposta."
        return out
    try:
        out["resposta"] = (groq_ia.gerar_resposta_ia(script, prompt) or "").strip().strip('"')
    except Exception as e:
        out["erro"] = f"Geração falhou: {e}"
    return out
