"""
Ação "Enviar Boleto" — portada do bloco de `passo_1_solicitar` do desktop.
Envia 3 mensagens em sequência: aviso pré-boleto, código do boleto e pedido de
comprovante. Os textos são copiados do desktop (não reescrever).
"""
from app.db import agora_texto, atualizar_campos_pedido, obter_config_conta, obter_pedido
from app.services import boletos, mercadolivre
from app.services.logger import log_evento

MSG_PRE_BOLETO = (
    "Vamos gerar o boleto agora mesmo!\n\n"
    "Prontinho, boleto gerado! Só copiar todo o código de barras abaixo "
    "e pagar pelo aplicativo do seu Banco: 👇"
)


def _msg_comprovante(nome_loja):
    return f"Esperamos o comprovante! Att, Time {nome_loja}".strip()


def enviar_boleto(conta, order_id):
    """Executa o fluxo completo. Retorna (sucesso, detalhe)."""
    pedido = obter_pedido(conta, order_id)
    if pedido is None:
        return False, "Venda não encontrada para essa conta."
    if pedido.get("boleto_enviado"):
        return False, "Boleto já havia sido enviado para essa ordem."
    if not pedido.get("rastreio_enviado"):
        return False, "Envie o rastreio antes de enviar o boleto (regra do fluxo original)."

    if str(pedido.get("metodo_taxa") or "").strip().lower() == "pix":
        # Taxa cobrada via PIX: envia a chave em vez de boleto (regra do desktop).
        from app.services import pix
        return pix.enviar_chave(conta, order_id, pedido)

    nome_loja = (obter_config_conta(conta).get("nome_loja") or "").strip()
    if not nome_loja:
        return False, "Configure o nome da loja antes de enviar boletos (usado no comprovante)."

    boleto = boletos.buscar_proximo_boleto(conta, pedido.get("provedor_taxa"))
    if not boleto:
        log_evento(conta, "erro", f"Ordem {order_id}: nenhum boleto disponível cadastrado para essa conta.")
        return False, "Nenhum boleto disponível — cadastre mais boletos para essa conta."

    buyer_id = pedido.get("buyer_id")

    for texto, etapa in (
        (MSG_PRE_BOLETO, "aviso pré-boleto"),
        (boleto["codigo"], "código do boleto"),
        (_msg_comprovante(nome_loja), "pedido de comprovante"),
    ):
        sucesso, detalhe = mercadolivre.enviar_mensagem(conta, order_id, buyer_id, texto)
        if not sucesso:
            log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar {etapa} — {detalhe}")
            return False, detalhe

    # As 3 mensagens saíram: agora persiste.
    boletos.marcar_boleto_usado(boleto["id"])
    atualizar_campos_pedido(conta, order_id, {
        "boleto_enviado": True,
        "data_boleto": agora_texto(),
        "codigo_boleto": boleto["codigo"],
        "id_payment": boleto.get("id_payment"),
        "horario_boleto": boleto.get("horario"),
        "provedor": boleto.get("provedor", ""),
    })

    log_evento(conta, "sucesso", f"Ordem {order_id}: boleto enviado com sucesso!")
    return True, "Boleto enviado com sucesso (3 mensagens)."
