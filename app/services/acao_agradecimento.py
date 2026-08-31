"""
Ação "Agradecimento" — portada do bloco correspondente de
`passo_1_solicitar`: envia uma mensagem de agradecimento quando o boleto
já foi pago, avisando a previsão de entrega.
"""
from app.db import get_connection
from app.services import mercadolivre
from app.services.logger import log_evento

MSG_AGRADECIMENTO = (
    "Obrigado, o pagamento da taxa foi realizado! Vamos dar continuidade à entrega.\n"
    "O seu pedido vai chegar {data_entrega} no período da tarde! 😉"
)


def enviar_agradecimento(conta_id, venda_id, data_entrega):
    data_entrega = (data_entrega or "").strip()
    if not data_entrega:
        return False, "Informe a previsão de entrega."

    conn = get_connection()
    venda = conn.execute(
        "SELECT * FROM vendas WHERE id = ? AND conta_id = ?", (venda_id, conta_id)
    ).fetchone()
    conn.close()

    if not venda:
        return False, "Venda não encontrada para essa conta."

    if not venda["boleto_pago"]:
        return False, "O boleto ainda não está marcado como pago para essa venda."

    if venda["boleto_pago_agradecimento"]:
        return False, "O agradecimento já havia sido enviado para essa ordem."

    texto = MSG_AGRADECIMENTO.format(data_entrega=data_entrega)
    sucesso, detalhe = mercadolivre.enviar_mensagem(
        conta_id, venda["order_id"], venda["buyer_id"], texto
    )

    if sucesso:
        conn = get_connection()
        conn.execute(
            "UPDATE vendas SET boleto_pago_agradecimento = 1 WHERE id = ?", (venda_id,)
        )
        conn.commit()
        conn.close()
        log_evento(conta_id, "sucesso", f"Ordem {venda['order_id']}: mensagem de agradecimento enviada.")
    else:
        log_evento(conta_id, "erro", f"Ordem {venda['order_id']}: falha ao enviar agradecimento — {detalhe}")

    return sucesso, detalhe
