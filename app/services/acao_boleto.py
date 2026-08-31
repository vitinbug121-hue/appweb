"""
Ação "Enviar Boleto" — portada do bloco correspondente de
`passo_1_solicitar` no sistema desktop original: envia 3 mensagens em
sequência (aviso pré-boleto, código do boleto, pedido de comprovante),
usando o próximo boleto disponível da conta (tabela `boletos_disponiveis`,
que substitui a antiga planilha `registros_pedidos.xlsx`).
"""
from datetime import datetime

from app.db import get_connection
from app.services import mercadolivre, boletos
from app.services.logger import log_evento

MSG_PRE_BOLETO = (
    "Vamos gerar o boleto agora mesmo!\n\n"
    "Prontinho, boleto gerado! Só copiar todo o código de barras abaixo "
    "e pagar pelo aplicativo do seu Banco:"
)
MSG_COMPROVANTE = "Esperamos o comprovante! Att, Time da loja."


def enviar_boleto(conta_id, venda_id):
    """Executa o fluxo completo de envio de boleto. Retorna (sucesso, detalhe)."""
    conn = get_connection()
    venda = conn.execute(
        "SELECT * FROM vendas WHERE id = ? AND conta_id = ?", (venda_id, conta_id)
    ).fetchone()
    conn.close()

    if not venda:
        return False, "Venda não encontrada para essa conta."

    if venda["boleto_enviado"]:
        return False, "Boleto já havia sido enviado para essa ordem."

    if not venda["rastreio_enviado"]:
        return False, "Envie o rastreio antes de enviar o boleto (regra do fluxo original)."

    boleto = boletos.buscar_proximo_boleto_disponivel(conta_id)
    if not boleto:
        log_evento(conta_id, "erro", f"Ordem {venda['order_id']}: nenhum boleto disponível cadastrado para essa conta.")
        return False, "Nenhum boleto disponível — cadastre mais boletos para essa conta."

    order_id, buyer_id = venda["order_id"], venda["buyer_id"]

    sucesso, detalhe = mercadolivre.enviar_mensagem(conta_id, order_id, buyer_id, MSG_PRE_BOLETO)
    if not sucesso:
        log_evento(conta_id, "erro", f"Ordem {order_id}: falha ao enviar aviso pré-boleto — {detalhe}")
        return False, detalhe

    sucesso, detalhe = mercadolivre.enviar_mensagem(conta_id, order_id, buyer_id, boleto["codigo"])
    if not sucesso:
        log_evento(conta_id, "erro", f"Ordem {order_id}: falha ao enviar código do boleto — {detalhe}")
        return False, detalhe

    sucesso, detalhe = mercadolivre.enviar_mensagem(conta_id, order_id, buyer_id, MSG_COMPROVANTE)
    if not sucesso:
        log_evento(conta_id, "erro", f"Ordem {order_id}: falha ao enviar pedido de comprovante — {detalhe}")
        return False, detalhe

    # As 3 mensagens saíram — agora persiste tudo
    boletos.marcar_boleto_usado(boleto["id"])

    conn = get_connection()
    conn.execute(
        """UPDATE vendas
           SET boleto_enviado = 1, data_boleto = ?, codigo_boleto = ?,
               id_payment = ?, horario_boleto = ?
           WHERE id = ?""",
        (
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            boleto["codigo"],
            boleto["id_payment"],
            boleto["horario"],
            venda_id,
        ),
    )
    conn.commit()
    conn.close()

    log_evento(conta_id, "sucesso", f"Ordem {order_id}: boleto enviado com sucesso!")
    return True, "Boleto enviado com sucesso (3 mensagens)."
