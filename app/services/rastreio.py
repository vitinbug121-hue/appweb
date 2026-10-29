"""
Ação "Enviar Rastreio" — portada de `passo_1_solicitar` (bloco de rastreio).

Os textos são IDÊNTICOS aos do desktop: foram extraídos do main.py e passados
pelo mesmo tratamento (textwrap.dedent + strip). Não editar à mão.

Tipo (igual ao desktop):
    'br'         -> Correios (tipomsgRastreio != 2)
    'aliexpress' -> 4tracking (tipomsgRastreio == 2)

Diferença deliberada em relação ao desktop: aqui o nome da loja é obrigatório,
porque sem ele a assinatura sairia como "(  )".
"""
from app.db import agora_texto, atualizar_campos_pedido, obter_config_conta, obter_pedido
from app.services import mercadolivre
from app.services.logger import log_evento

TIPOS_RASTREIO = {"br", "aliexpress"}

TEXTO_RASTREIO_BR = 'ACOMPANHE O SEU PEDIDO\nSegue abaixo o seu código de rastreamento:\n\n>>> {codigo} \n\nPara rastrear, basta acessar o site oficial dos Correios 👇\nhttps://rastreamento.correios.com.br/app/index.php\n\nLembrando que:\n\nO produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status. Mas não se preocupe, o seu pedido já está a caminho.\n\nDúvidas? Estamos à disposição! 😉\n\n( {nome_loja} )'

TEXTO_RASTREIO_ALIEXPRESS = 'ACOMPANHE O SEU PEDIDO\nSeu pedido já foi postado. Segue abaixo, seu código de rastreamento:\n\n>>> {codigo} \n\nPara rastrear, basta acessar o site da 4tracking e colar o código, só colocar no google 4tracking,é o site que faz o rastreio da transportadora.\n👉 https://www.4tracking.net/pt/tjax/track?nums={codigo}\n\nLembrando que:\n\nO produto é importado e PODE SER TAXADO, mas é bem difícil! O pedido é entregue pela transportadora, os Correios apenas fazem o rastreamento e podem demorar até 3 dias para atualizar o status. Mas não se preocupe, o seu pedido já está a caminho.\n\nDúvidas? Estamos à disposição! 😉\n\n( {nome_loja} )'

def _texto_rastreio(tipo, codigo, nome_loja):
    modelo = TEXTO_RASTREIO_ALIEXPRESS if tipo == "aliexpress" else TEXTO_RASTREIO_BR
    return modelo.format(codigo=codigo, nome_loja=nome_loja)


def enviar_rastreio(conta, order_id, codigo_rastreio, tipo="br"):
    """Valida, envia a mensagem pelo ML, grava o resultado e registra log.
    Retorna (sucesso, detalhe)."""
    codigo_rastreio = (codigo_rastreio or "").strip()
    if not codigo_rastreio:
        return False, "Informe o código de rastreio."
    if tipo not in TIPOS_RASTREIO:
        return False, "Tipo de rastreio inválido (use BR ou AliExpress)."

    nome_loja = (obter_config_conta(conta).get("nome_loja") or "").strip()
    if not nome_loja:
        return False, "Configure o nome da loja em Configurações antes de enviar rastreios (aparece na assinatura)."

    pedido = obter_pedido(conta, order_id)
    if pedido is None:
        return False, "Venda não encontrada para essa conta."
    if pedido.get("rastreio_enviado"):
        return False, "Rastreio já havia sido enviado para essa ordem."

    texto = _texto_rastreio(tipo, codigo_rastreio, nome_loja)
    sucesso, detalhe = mercadolivre.enviar_mensagem(conta, order_id, pedido.get("buyer_id"), texto)

    if sucesso:
        atualizar_campos_pedido(conta, order_id, {
            "rastreio_enviado": True,
            "data_rastreio": agora_texto(),
            "codigo_rastreio": codigo_rastreio,
            "tipo_rastreio": "aliexpress" if tipo == "aliexpress" else "br",
        })
        log_evento(conta, "sucesso", f"Ordem {order_id}: rastreio enviado com sucesso.")
    else:
        log_evento(conta, "erro", f"Ordem {order_id}: falha ao enviar rastreio — {detalhe}")

    return sucesso, detalhe
