"""
Etapa 3 — Erro no boleto, reenviar boleto, cobrar dobrado e reenviar dobrado
(portados dos ramos `erro_boleto`, `reenviar_boleto`, `cobrar_dobrado` e
`reenviar_boleto_dobrado` do desktop, dentro de `passo_1_solicitar`).

Textos copiados do desktop. Não reescrever.

Diferenças deliberadas em relação ao desktop (ver resposta):
  - O boleto do reenvio dobrado é do MESMO provedor da taxa (no desktop não
    é filtrado, o que pode gastar boleto da outra operadora).
  - Pedidos cobrados via PIX (taxa ou dobro) não recebem boleto.
  - Sem o provedor escolhido, nenhum boleto é gasto: a execução para.
"""
from app.db import (
    agora_texto,
    atualizar_campos_pedido,
    buscar_proximo_boleto,
    listar_pedidos,
    marcar_boleto_usado,
    obter_config_conta,
)
from app.services import autorizacao, mercadolivre
from app.services.acao_boleto import MSG_PRE_BOLETO, _msg_comprovante
from app.services.loja import formatar_valor_br, obter_loja, parse_valor_br
from app.services.logger import log_evento

MSG_ERRO_BOLETO = (
    "Olá, tudo bem?\n"
    "Por favor, desconsidere o código de barras enviado anteriormente, pois houve um erro na atualização do sistema.\n"
    "Segue o novo código de barras para pagamento da taxa: 👇\n"
)
MSG_ATRASO_BOLETO = (
    "Olá! Passando para pedir desculpas pela demora no envio do seu boleto. "
    "Tivemos uma pequena instabilidade, mas já foi resolvido! 👍"
)
MSG_ATRASO_DOBRO = (
    "Olá! Passando para pedir desculpas pela demora no envio do restante da taxa. "
    "Tivemos uma pequena instabilidade, mas já foi resolvido! 👍"
)
MSG_COBRANCA_DOBRO = (
    "Olá, tudo bem?\n\n"
    "Ocorreu um erro aqui de comunicação com a transportadora e a receita\n\n"
    "A taxa era R${mais_cem} e passaram R${taxa}, foi um erro da transportadora\n\n"
    "Falta mais R$100 pra pagar a taxa, para a transportadora entregar o seu painel que chegará na {data_entrega}"
)
FRASE_REENVIO_BOLETO = "Estamos gerando seu boleto. Aguarde um momento, por favor."
FRASE_REENVIO_DOBRO = "Estamos gerando seu Boleto do restante da taxa. Aguarde um momento, por favor."


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _enviar(conta, order_id, buyer_id, texto, etapa):
    ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, texto)
    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar {etapa} — {detalhe}")
    return ok


def _valor_taxa(dados):
    """Valor gravado na venda; se não houver (venda antiga), o valor atual da loja."""
    valor = dados.get("valor_taxa")
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _cliente_respondeu_frase(conta, order_id, pack_id, frase):
    """Verifica se a LOJA já enviou a frase no chat (mesmo critério do desktop)."""
    alvo = frase.lower()
    conversa = mercadolivre.obter_conversa(conta, order_id, pack_id)
    return any(m.get("is_seller") and alvo in (m.get("texto") or "").lower() for m in conversa)


def _filtrar_lote(conta, candidatos, lote_numero):
    if not lote_numero:
        return candidatos
    lote = next((l for l in autorizacao.calcular_lotes(conta) if l["numero"] == int(lote_numero)), None)
    if not lote:
        return None
    ids = set(lote["ids"])
    return [oid for oid in candidatos if str(oid) in ids]


def _enviar_boleto(conta, order_id, buyer_id, boleto, nome_loja, com_pre, texto_inicial=None):
    """Sequência de envio do boleto. Retorna True se tudo saiu."""
    if texto_inicial and not _enviar(conta, order_id, buyer_id, texto_inicial, "mensagem inicial"):
        return False
    if com_pre and not _enviar(conta, order_id, buyer_id, MSG_PRE_BOLETO, "aviso pré-boleto"):
        return False
    if not _enviar(conta, order_id, buyer_id, boleto["codigo"], "código do boleto"):
        return False
    if not _enviar(conta, order_id, buyer_id, _msg_comprovante(nome_loja), "pedido de comprovante"):
        return False
    return True


def _nome_loja_obrigatorio(conta):
    nome = (obter_config_conta(conta).get("nome_loja") or "").strip()
    return nome or None


# ---------------------------------------------------------------------------
# 1) Erro no boleto: manda código corrigido para quem já recebeu boleto e não pagou
# ---------------------------------------------------------------------------
def erro_boleto(conta, lote_numero=None):
    nome = _nome_loja_obrigatorio(conta)
    if not nome:
        return {"erro": "Configure o nome da loja antes de reenviar boletos."}

    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_enviado") and not pedidos[oid].get("boleto_pago")
        and not pedidos[oid].get("pago_via_pix") and pedidos[oid].get("metodo_taxa") != "pix"
        and pedidos[oid].get("buyer_id")
    ]
    candidatos = _filtrar_lote(conta, candidatos, lote_numero)
    if candidatos is None:
        return {"erro": f"Lote {lote_numero} não encontrado."}

    resumo = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0}
    for order_id in candidatos:
        dados = pedidos[order_id]
        boleto = buscar_proximo_boleto(conta, dados.get("provedor_taxa"))
        if not boleto:
            log_evento(conta, "erro", f"Ordem {order_id}: nenhum boleto disponível. Processamento interrompido.")
            resumo["erro"] = "Nenhum boleto disponível — processamento interrompido."
            break

        if not _enviar_boleto(conta, order_id, dados["buyer_id"], boleto, nome,
                              com_pre=False, texto_inicial=MSG_ERRO_BOLETO):
            resumo["falhas"] += 1
            continue

        marcar_boleto_usado(boleto["id"])
        atualizar_campos_pedido(conta, order_id, {
            "boleto_enviado": True,
            "data_boleto": agora_texto(),
            "codigo_boleto": boleto["codigo"],
            "id_payment": boleto.get("id_payment"),
            "horario_boleto": boleto.get("horario"),
            "provedor": boleto.get("provedor", ""),
        })
        resumo["enviados"] += 1
        log_evento(conta, "sucesso", f"Ordem {order_id}: boleto corrigido enviado.")

    log_evento(conta, "sucesso", f"Erro no boleto finalizado. Enviados: {resumo['enviados']} | Falhas: {resumo['falhas']}")
    return resumo


# ---------------------------------------------------------------------------
# 2) Reenviar boleto: para quem tem boleto enviado mas não pagou
# ---------------------------------------------------------------------------
def reenviar_boleto(conta, atraso=False, filtrar_frase=False, lote_numero=None):
    nome = _nome_loja_obrigatorio(conta)
    if not nome:
        return {"erro": "Configure o nome da loja antes de reenviar boletos."}

    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_enviado") and not pedidos[oid].get("boleto_pago")
        and not pedidos[oid].get("reenvio_confirmado") and pedidos[oid].get("buyer_id")
        and not pedidos[oid].get("pago_via_pix") and pedidos[oid].get("metodo_taxa") != "pix"
    ]
    candidatos = _filtrar_lote(conta, candidatos, lote_numero)
    if candidatos is None:
        return {"erro": f"Lote {lote_numero} não encontrado."}

    if filtrar_frase:
        autorizados = []
        for oid in candidatos:
            if _cliente_respondeu_frase(conta, oid, pedidos[oid].get("pack_id"), FRASE_REENVIO_BOLETO):
                atualizar_campos_pedido(conta, oid, {"cliente_autorizou_reenvio": True})
                pedidos[oid]["cliente_autorizou_reenvio"] = True  # mantém o dicionário em memória coerente com o banco
                autorizados.append(oid)
        candidatos = autorizados
        if not candidatos:
            return {"erro": "Nenhum cliente autorizou pela frase de reenvio. Reenvio cancelado."}

    resumo = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0}
    for order_id in candidatos:
        dados = pedidos[order_id]
        if filtrar_frase and not dados.get("cliente_autorizou_reenvio"):
            continue

        if atraso and not _enviar(conta, order_id, dados["buyer_id"], MSG_ATRASO_BOLETO, "mensagem de atraso"):
            resumo["falhas"] += 1
            continue

        boleto = buscar_proximo_boleto(conta, dados.get("provedor_taxa"))
        if not boleto:
            log_evento(conta, "erro", f"Ordem {order_id}: nenhum boleto disponível. Processamento interrompido.")
            resumo["erro"] = "Nenhum boleto disponível — processamento interrompido."
            break

        if not _enviar_boleto(conta, order_id, dados["buyer_id"], boleto, nome, com_pre=True):
            resumo["falhas"] += 1
            continue

        marcar_boleto_usado(boleto["id"])
        campos = {
            "boleto_enviado": True,
            "data_boleto": agora_texto(),
            "codigo_boleto": boleto["codigo"],
            "id_payment": boleto.get("id_payment"),
            "horario_boleto": boleto.get("horario"),
            "provedor": boleto.get("provedor", ""),
        }
        if filtrar_frase:
            campos["reenvio_confirmado"] = True
        atualizar_campos_pedido(conta, order_id, campos)
        resumo["enviados"] += 1
        log_evento(conta, "sucesso", f"Ordem {order_id}: boleto reenviado com sucesso.")

    log_evento(conta, "sucesso", f"Reenvio de boleto finalizado. Enviados: {resumo['enviados']} | Falhas: {resumo['falhas']}")
    return resumo


# ---------------------------------------------------------------------------
# 3) Cobrar dobrado: segunda parte da taxa (erro da transportadora)
# ---------------------------------------------------------------------------
def cobrar_dobrado(conta, metodo, data_entrega, lote_numero=None):
    if metodo not in ("pix", "boleto"):
        return {"erro": "Forma de cobrança inválida (use PIX ou boleto)."}
    data_entrega = (data_entrega or "").strip()
    if not data_entrega:
        return {"erro": "Informe a data de entrega (aparece na mensagem)."}

    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("boleto_pago") and pedidos[oid].get("boleto_pago_agradecimento")
        and not pedidos[oid].get("cobrado_dobro") and pedidos[oid].get("buyer_id")
    ]
    candidatos = _filtrar_lote(conta, candidatos, lote_numero)
    if candidatos is None:
        return {"erro": f"Lote {lote_numero} não encontrado."}

    valor_padrao = parse_valor_br(obter_loja(conta)["valor_boleto"]) or 0.0
    resumo = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0}
    for order_id in candidatos:
        dados = pedidos[order_id]
        taxa = _valor_taxa(dados) or valor_padrao
        texto = MSG_COBRANCA_DOBRO.format(
            mais_cem=formatar_valor_br(taxa + 100),
            taxa=formatar_valor_br(taxa),
            data_entrega=data_entrega,
        )
        if not _enviar(conta, order_id, dados["buyer_id"], texto, "cobrança dobrada"):
            resumo["falhas"] += 1
            continue

        atualizar_campos_pedido(conta, order_id, {
            "cobrado_dobro": True,
            "data_cobro_dobro": agora_texto(),
            "metodo_cobro_dobro": metodo,
        })
        resumo["enviados"] += 1
        log_evento(conta, "sucesso", f"Ordem {order_id}: cobrança dobrada enviada ({'PIX' if metodo == 'pix' else 'boleto'}).")

    log_evento(conta, "sucesso", f"Cobrança dobrada finalizada. Enviados: {resumo['enviados']} | Falhas: {resumo['falhas']}")
    return resumo


# ---------------------------------------------------------------------------
# 4) Reenviar boleto dobrado
# ---------------------------------------------------------------------------
def reenviar_boleto_dobrado(conta, atraso=False, filtrar_frase=False, lote_numero=None):
    nome = _nome_loja_obrigatorio(conta)
    if not nome:
        return {"erro": "Configure o nome da loja antes de reenviar boletos."}

    pedidos = listar_pedidos(conta)
    candidatos = [
        oid for oid in sorted(pedidos)
        if pedidos[oid].get("cobrado_dobro") and not pedidos[oid].get("boleto_pago_dobro")
        and pedidos[oid].get("metodo_cobro_dobro", "boleto") == "boleto"
        and not pedidos[oid].get("reenvio_confirmado_dobro") and pedidos[oid].get("buyer_id")
    ]
    candidatos = _filtrar_lote(conta, candidatos, lote_numero)
    if candidatos is None:
        return {"erro": f"Lote {lote_numero} não encontrado."}

    if filtrar_frase:
        autorizados = []
        for oid in candidatos:
            if _cliente_respondeu_frase(conta, oid, pedidos[oid].get("pack_id"), FRASE_REENVIO_DOBRO):
                atualizar_campos_pedido(conta, oid, {"cliente_autorizou_reenvio_dobro": True})
                pedidos[oid]["cliente_autorizou_reenvio_dobro"] = True  # mantém o dicionário em memória coerente com o banco
                autorizados.append(oid)
        candidatos = autorizados
        if not candidatos:
            return {"erro": "Nenhum cliente autorizou pela frase de reenvio dobrado. Reenvio cancelado."}

    resumo = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0}
    for order_id in candidatos:
        dados = pedidos[order_id]
        if filtrar_frase and not dados.get("cliente_autorizou_reenvio_dobro"):
            continue

        if atraso and not _enviar(conta, order_id, dados["buyer_id"], MSG_ATRASO_DOBRO, "mensagem de atraso (dobro)"):
            resumo["falhas"] += 1
            continue

        boleto = buscar_proximo_boleto(conta, dados.get("provedor_taxa"))
        if not boleto:
            log_evento(conta, "erro", f"Ordem {order_id}: nenhum boleto disponível. Processamento interrompido.")
            resumo["erro"] = "Nenhum boleto disponível — processamento interrompido."
            break

        if not _enviar_boleto(conta, order_id, dados["buyer_id"], boleto, nome, com_pre=True):
            resumo["falhas"] += 1
            continue

        marcar_boleto_usado(boleto["id"])
        campos = {
            "codigo_boleto_dobro": boleto["codigo"],
            "id_payment_dobro": boleto.get("id_payment"),
            "horario_boleto_dobro": boleto.get("horario"),
            "provedor_dobro": boleto.get("provedor", ""),
            "data_reenvio_dobro": agora_texto(),
        }
        if filtrar_frase:
            campos["reenvio_confirmado_dobro"] = True
        atualizar_campos_pedido(conta, order_id, campos)
        resumo["enviados"] += 1
        log_evento(conta, "sucesso", f"Ordem {order_id}: boleto dobrado reenviado com sucesso.")

    log_evento(conta, "sucesso", f"Reenvio de boleto dobrado finalizado. Enviados: {resumo['enviados']} | Falhas: {resumo['falhas']}")
    return resumo
