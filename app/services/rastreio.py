"""
Ação "Enviar Rastreio" — portada de `passo_1_solicitar` (bloco de rastreio)
do sistema desktop original, agora como uma função isolada e testável,
sem nenhuma dependência de Tkinter.
"""
from datetime import datetime

from app.db import get_connection
from app.services import mercadolivre
from app.services.logger import log_evento

TEXTO_PADRAO = (
    "ACOMPANHE O SEU PEDIDO\n"
    "Segue abaixo o seu código de rastreamento:\n\n"
    ">>> {codigo}\n\n"
    "Para rastrear, acesse o site oficial dos Correios:\n"
    "https://rastreamento.correios.com.br/app/index.php\n\n"
    "Lembrando que o produto é importado e pode ser taxado, mas isso é raro. "
    "Dúvidas? Estamos à disposição!"
)


def enviar_rastreio(conta_id, venda_id, codigo_rastreio):
    """Executa o fluxo completo: valida a venda, envia a mensagem via ML,
    atualiza a venda no banco e registra o log. Retorna (sucesso, detalhe)."""
    codigo_rastreio = (codigo_rastreio or "").strip()
    if not codigo_rastreio:
        return False, "Informe o código de rastreio."

    conn = get_connection()
    venda = conn.execute(
        "SELECT * FROM vendas WHERE id = ? AND conta_id = ?", (venda_id, conta_id)
    ).fetchone()

    if not venda:
        conn.close()
        return False, "Venda não encontrada para essa conta."

    if venda["rastreio_enviado"]:
        conn.close()
        return False, "Rastreio já havia sido enviado para essa ordem."

    conn.close()

    texto = TEXTO_PADRAO.format(codigo=codigo_rastreio)
    sucesso, detalhe = mercadolivre.enviar_mensagem(
        conta_id, venda["order_id"], venda["buyer_id"], texto
    )

    if sucesso:
        conn = get_connection()
        conn.execute(
            """UPDATE vendas
               SET rastreio_enviado = 1, data_rastreio = ?, codigo_rastreio = ?
               WHERE id = ?""",
            (datetime.now().strftime("%d/%m/%Y %H:%M"), codigo_rastreio, venda_id),
        )
        conn.commit()
        conn.close()
        log_evento(conta_id, "sucesso", f"Ordem {venda['order_id']}: rastreio enviado com sucesso.")
    else:
        log_evento(conta_id, "erro", f"Ordem {venda['order_id']}: falha ao enviar rastreio — {detalhe}")

    return sucesso, detalhe
