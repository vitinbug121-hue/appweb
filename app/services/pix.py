"""
Etapa 5 — PIX (portada de: envio da chave PIX dentro da ação de boleto,
"Atualizar PIX Pagos" e "AVISO PIX → BOLETO" do desktop).

  * enviar_chave: para pedidos com taxa via PIX (metodo_taxa='pix'), envia o
    aviso, a chave e o comprovante. Chamado pelo botão "Enviar boleto" quando
    o pedido é PIX (o desktop trata assim).
  * atualizar_pix_pagos: lê o chat de pedidos PIX pendentes e marca como pago
    quando a LOJA enviou a frase de confirmação.
  * aviso_pix_para_boleto: para quem pediu a chave PIX e não pagou, troca para
    boleto ASAAS. Usa os mesmos critérios de resposta da Etapa 4 (com trava de
    confirmação, porque a verificação por IA ainda não existe na web).

Textos copiados do desktop. Não reescrever.
"""
import re
import time
from datetime import datetime

from app.db import (
    obter_pedido,
    agora_texto,
    atualizar_campos_pedido,
    buscar_proximo_boleto,
    listar_pedidos,
    marcar_boleto_usado,
    obter_config_conta,
    obter_pedido,
)
from app.services import autorizacao, groq_ia, mercadolivre
from app.services.acao_boleto import MSG_PRE_BOLETO, _msg_comprovante
from app.services.loja import formatar_valor_br, obter_loja, parse_valor_br
from app.services.controle import ParadaSolicitada
from app.services.logger import log_evento
from app.services.pendencias import PADRAO_MSG_COMPENSACAO, _e_resposta_1, _parece_codigo_boleto

FRASE_CONFIRMACAO_PIX = "Recebemos o pagamento da Taxa."
PADRAO_PROMPT_CHAVE_PIX = re.compile(r"digite\s*1\b.{0,150}enviar a chave pix", re.IGNORECASE | re.DOTALL)
PAUSA_ENTRE_PEDIDOS = 0.5

MSG_PRE_PIX = (
    "Vamos gerar o pagamento agora mesmo!\n\n"
    "Para pagar a taxa de R$ {valor} via PIX, é só copiar a chave PIX abaixo e pagar pelo aplicativo do seu Banco: 👇"
)
MSG_AVISO_PIX_PARA_BOLETO = (
    "Olá! Infelizmente tivemos um problema com a chave PIX. Por isso, a cobrança da taxa será feita "
    "pelo boleto da empresa com mais segurança. Desculpe pelo transtorno! 🙏"
)


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def cobranca_pix_pendente(d):
    """Taxa via PIX autorizada que ainda não recebeu boleto, não foi paga e não foi convertida."""
    if d.get("boleto_enviado") or not d.get("boleto_autorizado_msg"):
        return False
    eh_pix = str(d.get("metodo_taxa") or "").strip().lower() == "pix" or bool(d.get("cobrado_via_pix"))
    if not eh_pix:
        return False
    return not (d.get("pago_via_pix") or d.get("boleto_pago") or d.get("aviso_pix_boleto"))


def cliente_pediu_chave(conversa):
    """True se o cliente respondeu '1' após o prompt 'DIGITE 1 ... enviar a chave PIX'."""
    indice = None
    for idx, m in enumerate(conversa):
        if PADRAO_PROMPT_CHAVE_PIX.search((m.get("texto") or "").strip()):
            indice = idx
    if indice is None:
        return False
    for m in conversa[indice + 1:]:
        if m.get("is_seller"):
            continue
        texto = (m.get("texto") or "").strip()
        if not texto or PADRAO_MSG_COMPENSACAO.search(texto) or _parece_codigo_boleto(texto):
            continue
        if _e_resposta_1(texto):
            return True
    return False


def cliente_pediu_chave_com_ia(conversa):
    """Fallback pela IA: mensagens do cliente após o prompt de chave PIX, sem '1' isolado."""
    indice = None
    for idx, m in enumerate(conversa):
        if PADRAO_PROMPT_CHAVE_PIX.search((m.get("texto") or "").strip()):
            indice = idx
    if indice is None:
        return False
    textos = []
    for m in conversa[indice + 1:]:
        texto = (m.get("texto") or "").strip()
        if m.get("is_seller") or not texto:
            continue
        if PADRAO_MSG_COMPENSACAO.search(texto) or _parece_codigo_boleto(texto):
            continue
        textos.append(texto)
    return groq_ia.verificar_intencao(textos)


def texto_recebedor(config):
    """'Nome: X\\n\\nBanco: Y' (vazio se ambos vazios). Igual ao desktop."""
    linhas = []
    if config.get("nome_recebedor_pix"):
        linhas.append(f"Nome: {config['nome_recebedor_pix']}")
    if config.get("banco_pix"):
        linhas.append(f"Banco: {config['banco_pix']}")
    return "\n\n".join(linhas)


# ---------------------------------------------------------------------------
# 1) Envio da chave PIX (pedido com taxa via PIX)
# ---------------------------------------------------------------------------
def enviar_chave(conta, order_id, pedido):
    """Retorna (ok, detalhe). Usado pelo botão 'Enviar boleto' para pedidos PIX."""
    config = obter_config_conta(conta)
    chave = (config.get("chave_pix") or "").strip()
    nome = (config.get("nome_loja") or "").strip()
    if not chave:
        return False, "Configure a chave PIX em Configurações antes de enviar taxas via PIX."
    if not nome:
        return False, "Configure o nome da loja antes de enviar taxas via PIX."

    valor = _valor_taxa(pedido, conta)
    buyer_id = pedido.get("buyer_id")
    if not _enviar(conta, order_id, buyer_id, MSG_PRE_PIX.format(valor=formatar_valor_br(valor)), "aviso PIX"):
        return False, "Falha ao enviar aviso PIX."
    if not _enviar(conta, order_id, buyer_id, chave, "chave PIX"):
        return False, "Falha ao enviar a chave PIX."

    recebedor = texto_recebedor(config)
    prefixo = f"\n{recebedor}\n\n" if recebedor else ""
    comprovante = f"{prefixo}{_msg_comprovante(nome)}".strip()
    if not _enviar(conta, order_id, buyer_id, comprovante, "comprovante PIX"):
        return False, "Falha ao enviar o pedido de comprovante PIX."

    atualizar_campos_pedido(conta, order_id, {
        "boleto_enviado": True,
        "data_boleto": agora_texto(),
        "codigo_boleto": chave,
        "cobrado_via_pix": True,
        "chave_pix": chave,
    })
    log_evento(conta, "sucesso", f"Ordem {order_id}: chave PIX enviada.")
    return True, "Chave PIX enviada com sucesso (3 mensagens)."


def _valor_taxa(pedido, conta):
    try:
        if pedido.get("valor_taxa") not in (None, ""):
            return float(pedido["valor_taxa"])
    except (TypeError, ValueError):
        pass
    return parse_valor_br(obter_loja(conta)["valor_boleto"]) or 0.0


def _enviar(conta, order_id, buyer_id, texto, etapa):
    ok, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, texto)
    if not ok:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar {etapa} — {detalhe}")
    return ok


# ---------------------------------------------------------------------------
# 2) Atualizar PIX pagos
# ---------------------------------------------------------------------------
def atualizar_pix_pagos(conta):
    pedidos = listar_pedidos(conta)
    pendentes = [
        oid for oid, d in sorted(pedidos.items())
        if (d.get("metodo_cobro_dobro") == "pix" and not d.get("pago_dobro_pix"))
        or (d.get("cobrado_via_pix") and not d.get("pago_via_pix"))
    ]
    resumo = {"verificados": len(pendentes), "pagos": 0, "erros": 0}
    if not pendentes:
        log_evento(conta, "aviso", "Nenhuma venda cobrada via PIX pendente de confirmação.")
        return resumo

    for oid in pendentes:
        d = pedidos[oid]
        try:
            conversa = mercadolivre.obter_conversa(conta, oid, d.get("pack_id"))
            # Só a LOJA pode confirmar: a mesma frase escrita pelo cliente é ignorada.
            achou = any(
                m.get("is_seller") and FRASE_CONFIRMACAO_PIX.lower() in (m.get("texto") or "").lower()
                for m in conversa
            )
            if not achou:
                log_evento(conta, "aviso", f"Ordem {oid}: frase de confirmação do PIX ainda não encontrada.")
                continue

            agora = agora_texto()
            if d.get("cobrado_via_pix") and not d.get("pago_via_pix"):
                campos = {"pago_via_pix": True, "data_pago_via_pix": agora}
            else:
                campos = {"pago_dobro_pix": True, "data_pago_dobro_pix": agora}
            atualizar_campos_pedido(conta, oid, campos)
            resumo["pagos"] += 1
            log_evento(conta, "sucesso", f"Ordem {oid}: pagamento PIX confirmado no chat.")
        except ParadaSolicitada:
            raise
        except Exception as e:
            resumo["erros"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: erro ao verificar PIX — {e}")
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(conta, "sucesso", f"Atualização de PIX finalizada. Verificados: {resumo['verificados']} | "
                                 f"Pagos: {resumo['pagos']} | Erros: {resumo['erros']}")
    return resumo


# ---------------------------------------------------------------------------
# 3) Aviso PIX → boleto ASAAS
# ---------------------------------------------------------------------------
def aviso_pix_para_boleto(conta, lote_numero=None):
    nome = (obter_config_conta(conta).get("nome_loja") or "").strip()
    if not nome:
        return {"erro": "Configure o nome da loja antes de enviar boletos."}

    pedidos = listar_pedidos(conta)
    candidatos = [oid for oid in sorted(pedidos) if cobranca_pix_pendente(pedidos[oid]) and pedidos[oid].get("buyer_id")]
    if lote_numero:
        lote = next((l for l in autorizacao.calcular_lotes(conta) if l["numero"] == int(lote_numero)), None)
        if not lote:
            return {"erro": f"Lote {lote_numero} não encontrado."}
        candidatos = [oid for oid in candidatos if str(oid) in set(lote["ids"])]

    resumo = {"candidatos": len(candidatos), "enviados": 0, "nao_pediram_pix": 0, "sem_boleto": 0, "falhas": 0}
    for oid in candidatos:
        d = pedidos[oid]
        conversa = mercadolivre.obter_conversa(conta, oid, d.get("pack_id"))
        if not (cliente_pediu_chave(conversa) or cliente_pediu_chave_com_ia(conversa)):
            resumo["nao_pediram_pix"] += 1
            continue

        boleto = buscar_proximo_boleto(conta, "ASAAS")
        if not boleto:
            resumo["sem_boleto"] += 1
            log_evento(conta, "erro", f"Ordem {oid}: não há boleto ASAAS disponível. Venda pulada.")
            continue

        mensagens = [
            MSG_AVISO_PIX_PARA_BOLETO,
            MSG_PRE_BOLETO,
            str(boleto["codigo"]),
            _msg_comprovante(nome),
        ]
        falhou = False
        for texto in mensagens:
            if not _enviar(conta, oid, d["buyer_id"], texto, "aviso PIX → boleto"):
                falhou = True
                break
        if falhou:
            resumo["falhas"] += 1
            continue

        marcar_boleto_usado(boleto["id"])
        agora = agora_texto()
        atualizar_campos_pedido(conta, oid, {
            "boleto_enviado": True,
            "data_boleto": agora,
            "codigo_boleto": boleto["codigo"],
            "id_payment": boleto.get("id_payment"),
            "horario_boleto": boleto.get("horario"),
            "provedor": "ASAAS",
            "metodo_taxa": "boleto",
            "provedor_taxa": "ASAAS",
            "aviso_pix_boleto": True,
            "data_aviso_pix_boleto": agora,
            "cobrado_via_pix_anterior": bool(d.get("cobrado_via_pix")),
            "cobrado_via_pix": False,
        })
        resumo["enviados"] += 1
        log_evento(conta, "sucesso", f"Ordem {oid}: aviso PIX → boleto ASAAS enviado.")
        time.sleep(PAUSA_ENTRE_PEDIDOS)

    log_evento(conta, "sucesso",
               f"Aviso PIX → boleto finalizado. Enviados: {resumo['enviados']} | "
               f"Não pediram a chave: {resumo['nao_pediram_pix']} | Sem boleto ASAAS: {resumo['sem_boleto']} | "
               f"Falhas: {resumo['falhas']}")
    return resumo


def _separar_ordens(texto):
    """Aceita números separados por espaço, vírgula, ponto e vírgula ou quebra de linha."""
    vistos, saida = set(), []
    for item in re.split(r"[\s,;]+", texto or ""):
        item = item.strip()
        if item and item not in vistos:
            vistos.add(item)
            saida.append(item)
    return saida


def marcar_pagos_manual(conta, texto_ordens, tipo):
    """Baixa manual de cobranças via PIX. tipo = 'taxa' ou 'dobro'.
    Só marca pedidos cobrados via PIX e ainda não pagos. Devolve um resumo com os motivos."""
    if tipo not in ("taxa", "dobro"):
        return {"erro": "Tipo inválido."}
    ordens = _separar_ordens(texto_ordens)
    if not ordens:
        return {"erro": "Informe pelo menos um número de ordem."}

    resumo = {"total": len(ordens), "marcadas": [], "ignoradas": []}
    agora = agora_texto()
    for oid in ordens:
        d = obter_pedido(conta, oid)
        if d is None:
            resumo["ignoradas"].append((oid, "não encontrada nesta conta"))
            continue
        if tipo == "taxa":
            if not d.get("cobrado_via_pix"):
                resumo["ignoradas"].append((oid, "não foi cobrada via PIX"))
                continue
            if d.get("pago_via_pix"):
                resumo["ignoradas"].append((oid, "já estava paga"))
                continue
            campos = {"pago_via_pix": True, "data_pago_via_pix": agora, "pago_via_pix_manual": True}
        else:
            if str(d.get("metodo_cobro_dobro") or "").lower() != "pix":
                resumo["ignoradas"].append((oid, "dobro não foi cobrado via PIX"))
                continue
            if d.get("pago_dobro_pix"):
                resumo["ignoradas"].append((oid, "dobro já estava pago"))
                continue
            campos = {"pago_dobro_pix": True, "data_pago_dobro_pix": agora, "pago_dobro_pix_manual": True}

        atualizar_campos_pedido(conta, oid, campos)
        resumo["marcadas"].append(oid)
        log_evento(conta, "sucesso",
                   f"Ordem {oid}: {'taxa' if tipo == 'taxa' else 'dobro'} via PIX marcada como paga manualmente pelo operador.")

    log_evento(conta, "sucesso",
               f"Baixa manual de PIX: {len(resumo['marcadas'])} marcada(s), {len(resumo['ignoradas'])} ignorada(s).")
    return resumo
