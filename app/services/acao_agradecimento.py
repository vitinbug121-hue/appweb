"""
Ação "Agradecimento" — portada do bloco correspondente de `passo_1_solicitar`.
Texto copiado do desktop (não reescrever).
"""
from app.db import atualizar_campos_pedido, obter_pedido
from app.services import mercadolivre
from app.services.logger import log_evento

MSG_AGRADECIMENTO = (
    "Obrigado, o pagamento da taxa foi realizado. \n\n Vamos dar continuidade a entrega.\n\n"
    "O seu pedido vai chegar {data_entrega} no período da tarde! 😉"
)


def enviar_agradecimento(conta, order_id, data_entrega):
    data_entrega = (data_entrega or "").strip()
    if not data_entrega:
        return False, "Informe a previsão de entrega."

    pedido = obter_pedido(conta, order_id)
    if pedido is None:
        return False, "Venda não encontrada para essa conta."
    if not (pedido.get("boleto_pago") or pedido.get("pago_via_pix")):
        return False, "O boleto ainda não está marcado como pago para essa venda."
    if pedido.get("boleto_pago_agradecimento"):
        return False, "O agradecimento já havia sido enviado para essa ordem."

    texto = MSG_AGRADECIMENTO.format(data_entrega=data_entrega)
    sucesso, detalhe = mercadolivre.enviar_mensagem(conta, order_id, pedido.get("buyer_id"), texto)

    if sucesso:
        atualizar_campos_pedido(conta, order_id, {"boleto_pago_agradecimento": True})
        log_evento(conta, "sucesso", f"Ordem {order_id}: mensagem de agradecimento enviada.")
    else:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar agradecimento — {detalhe}")

    return sucesso, detalhe
