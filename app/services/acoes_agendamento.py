"""
Ações que podem ser agendadas (worker automático e botão "Executar agora").

Cada ação tem:
  - rotulo:         nome exibido no formulário
  - parametros:     campos pedidos no cadastro (guardados no agendamento)
  - envia_mensagem: manda mensagem ao comprador (exige confirmação no cadastro)
  - reembolsa:      movimenta dinheiro (exige confirmação no cadastro)
  - executar(conta, params) -> (ok: bool, detalhe: str)

Excluídas da agenda nesta versão:
  - boleto:   as regras de lote do desktop para envio em lote não foram verificadas.
  - rastreio: exige um código de rastreio digitado para cada pedido.
"""
import time

from app.db import listar_pedidos, obter_agendamento_bruto, registrar_historico
from app.services import (
    acao_agradecimento,
    autorizacao,
    brindes,
    cobrancas,
    encerradas,
    ia_conversa,
    ia_duvidas,
    mercadopago,
    asaas,
    pendencias,
    pix,
    solicitacao,
)
from app.services.controle import ParadaSolicitada
from app.services.logger import log_evento

PAUSA = 0.5


def _p(nome, rotulo, tipo="texto", obrigatorio=False, padrao=None):
    return {"nome": nome, "rotulo": rotulo, "tipo": tipo, "obrigatorio": obrigatorio, "padrao": padrao}


P_PRAZO = _p("prazo", "Prazo de entrega (texto)", obrigatorio=True)
P_OFFSET = _p("offset", "Offset inicial", "inteiro", padrao=0)
P_LIMITE = _p("limite", "Quantidade de pedidos", "inteiro", padrao=20)
P_FORMA = _p("forma", "Forma de cobrança (pix, mp, asaas)", obrigatorio=True)
P_DATA = _p("data_entrega", "Data de entrega", obrigatorio=True)
P_LOTE = _p("lote", "Número do lote (vazio = todos)", "inteiro")
P_ATRASO = _p("atraso", "Enviar pedido de desculpas antes", "bool")
P_FILTRO = _p("filtrar_frase", "Só para quem recebeu a frase de reenvio", "bool")
P_LIMITE_REEMB = _p("limite_reembolso", "Máximo de reembolsos por execução", "inteiro", padrao=10)


def _resultado(resumo, texto):
    if "erro" in resumo:
        return False, resumo["erro"]
    return resumo.get("falhas", 0) == 0, texto.format(**resumo)


# ---------------------------------------------------------------------------
# Execução de cada ação
# ---------------------------------------------------------------------------
def _solicitar(conta, p):
    r = solicitacao.solicitar_lote(conta, p.get("prazo", ""), p.get("offset", 0), p.get("limite", 20))
    return _resultado(r, "Enviadas: {enviadas} | Telefones: {numeros} | Falhas: {falhas}")


def _autorizar(conta, p):
    r = autorizacao.autorizar_lote(conta, p.get("forma", ""), p.get("data_entrega", ""),
                                   p.get("lote"), p.get("limite", 20))
    return _resultado(r, "Enviadas: {enviadas} | Falhas: {falhas}")


def _nao_pagos(conta, p):
    r = pendencias.cobrar_nao_pagos(conta, p.get("lote"))
    return _resultado(r, "Enviadas: {enviadas} | Aguardando 24h: {aguardando} | Falhas: {falhas}")


def _nao_autorizados(conta, p):
    r = pendencias.cobrar_nao_autorizados(conta, p.get("lote"))
    return _resultado(r, "Enviadas: {enviadas} | Já autorizaram: {ja_autorizaram} | Falhas: {falhas}")


def _cobrar_dobrado(conta, p):
    r = cobrancas.cobrar_dobrado(conta, p.get("forma", ""), p.get("data_entrega", ""), p.get("lote"))
    return _resultado(r, "Enviadas: {enviados} | Falhas: {falhas}")


def _erro_boleto(conta, p):
    r = cobrancas.erro_boleto(conta, p.get("lote"))
    return _resultado(r, "Enviados: {enviados} | Falhas: {falhas}")


def _reenviar_boleto(conta, p):
    r = cobrancas.reenviar_boleto(conta, atraso=p.get("atraso", False),
                                  filtrar_frase=p.get("filtrar_frase", False), lote_numero=p.get("lote"))
    return _resultado(r, "Enviados: {enviados} | Falhas: {falhas}")


def _reenviar_dobrado(conta, p):
    r = cobrancas.reenviar_boleto_dobrado(conta, atraso=p.get("atraso", False),
                                          filtrar_frase=p.get("filtrar_frase", False), lote_numero=p.get("lote"))
    return _resultado(r, "Enviados: {enviados} | Falhas: {falhas}")


def _aviso_pix(conta, p):
    r = pix.aviso_pix_para_boleto(conta, p.get("lote"))
    return _resultado(r, "Enviados: {enviados} | Falhas: {falhas}")


def _agradecimento(conta, p):
    data = (p.get("data_entrega") or "").strip()
    if not data:
        return False, "Informe a data de entrega."
    enviados = falhas = 0
    for oid, d in sorted(listar_pedidos(conta).items()):
        if not (d.get("boleto_pago") or d.get("pago_via_pix")) or d.get("boleto_pago_agradecimento"):
            continue
        if not d.get("buyer_id"):
            continue
        ok, _ = acao_agradecimento.enviar_agradecimento(conta, oid, data)
        enviados += ok
        falhas += not ok
        time.sleep(PAUSA)
    return falhas == 0, f"Enviados: {enviados} | Falhas: {falhas}"


def _ia_conversas(conta, p):
    r = ia_conversa.responder_lote(conta, p.get("limite", 20))
    return r["falhas"] == 0, f"Enviadas: {r['enviadas']} | Não precisam: {r['nao_precisa']} | Falhas: {r['falhas']}"


def _responder_duvidas(conta, p):
    r = ia_duvidas.responder_duvidas_pendentes(conta)
    return r["erros"] == 0, f"Respondidas: {r['respondidas']} | Erros: {r['erros']}"


def _atualizar_pagos(conta, p):
    r = mercadopago.atualizar_pagos(conta)
    return r["erros"] == 0, f"Verificados: {r['verificados']} | Pagos: {r['pagos']} | Erros: {r['erros']}"


def _atualizar_pix(conta, p):
    r = pix.atualizar_pix_pagos(conta)
    return r["erros"] == 0, f"Verificados: {r['verificados']} | Pagos: {r['pagos']} | Erros: {r['erros']}"


def _atualizar_asaas(conta, p):
    r = asaas.atualizar_asaas_pagos(conta)
    if "erro" in r:
        return False, r["erro"]
    return r["erros"] == 0, f"Verificados: {r['verificados']} | Pagos: {r['pagos']} | Erros: {r['erros']}"


def _atualizar_asaas_navegador(conta, p):
    r = asaas_selenium.atualizar_asaas_navegador(conta)
    if "erro" in r:
        return False, r["erro"]
    return r["erros"] == 0, f"Verificados: {r['verificados']} | Pagos: {r['pagos']} | Erros: {r['erros']}"


def _atualizar_e_reembolsar(conta, p):
    r = mercadopago.atualizar_pagos(conta)
    limite = p.get("limite_reembolso", 10)
    from app.db import listar_vendas_reembolsaveis
    pendentes = listar_vendas_reembolsaveis(conta)[:limite]
    reembolsados = falhas = 0
    for v in pendentes:
        ok, _ = mercadopago.reembolsar_venda(conta, v["order_id"])
        reembolsados += ok
        falhas += not ok
        time.sleep(PAUSA)
    ok = r["erros"] == 0 and falhas == 0
    return ok, (f"Pagos: {r['pagos']} | Reembolsados: {reembolsados} de {len(pendentes)} "
                f"(limite {limite}) | Falhas: {falhas}")


def _vendas_encerradas(conta, p):
    r = encerradas.atualizar_vendas_encerradas(conta)
    if "erro" in r:
        return False, r["erro"]
    return True, f"Analisados: {r['analisados']} | Marcados: {r['marcados']}"



def _brindes(conta, p):
    r = brindes.enviar_brindes_pendentes(conta)
    return r["falhas"] == 0, f"Enviados: {r['enviados']} | Falhas: {r['falhas']}"


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
ACOES = {
    "solicitar": {"rotulo": "Solicitar (primeira mensagem e telefone)", "parametros": [P_PRAZO, P_OFFSET, P_LIMITE], "envia_mensagem": True, "reembolsa": False, "executar": _solicitar},
    "autorizar_boleto": {"rotulo": "Taxar e autorizar", "parametros": [P_FORMA, P_DATA, P_LIMITE, P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _autorizar},
    "nao_pagos": {"rotulo": "Cobrar não pagos", "parametros": [P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _nao_pagos},
    "nao_autorizados": {"rotulo": "Cobrar não autorizados", "parametros": [P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _nao_autorizados},
    "cobrar_dobrado": {"rotulo": "Cobrar dobrado", "parametros": [P_FORMA, P_DATA, P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _cobrar_dobrado},
    "erro_boleto": {"rotulo": "Erro no boleto", "parametros": [P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _erro_boleto},
    "reenviar_boleto": {"rotulo": "Reenviar boleto", "parametros": [P_ATRASO, P_FILTRO, P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _reenviar_boleto},
    "reenviar_boleto_dobrado": {"rotulo": "Reenviar boleto dobrado", "parametros": [P_ATRASO, P_FILTRO, P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _reenviar_dobrado},
    "aviso_pix_boleto": {"rotulo": "Aviso PIX → boleto", "parametros": [P_LOTE], "envia_mensagem": True, "reembolsa": False, "executar": _aviso_pix},
    "agradecimento": {"rotulo": "Agradecimento", "parametros": [P_DATA], "envia_mensagem": True, "reembolsa": False, "executar": _agradecimento},
    "brindes": {"rotulo": "Enviar brindes pendentes", "parametros": [], "envia_mensagem": True, "reembolsa": False, "executar": _brindes},
    "ia": {"rotulo": "IA: responder chat e reclamações", "parametros": [P_LIMITE], "envia_mensagem": True, "reembolsa": False, "executar": _ia_conversas},
    "responder_duvidas_ml": {"rotulo": "Responder dúvidas ML (IA)", "parametros": [], "envia_mensagem": True, "reembolsa": False, "executar": _responder_duvidas},
    "atualizar_pagos": {"rotulo": "Atualizar pagos (Mercado Pago)", "parametros": [], "envia_mensagem": False, "reembolsa": False, "executar": _atualizar_pagos},
    "atualizar_asaas_pagos": {"rotulo": "Atualizar boletos Asaas pagos (API)", "parametros": [], "envia_mensagem": False, "reembolsa": False, "executar": _atualizar_asaas},
    "atualizar_asaas_navegador": {"rotulo": "Atualizar boletos Asaas pagos (navegador)", "parametros": [], "envia_mensagem": False, "reembolsa": False, "executar": _atualizar_asaas_navegador},
    "atualizar_pix_pagos": {"rotulo": "Atualizar PIX pagos", "parametros": [], "envia_mensagem": False, "reembolsa": False, "executar": _atualizar_pix},
    "atualizar_pagos_reembolsar": {"rotulo": "Atualizar pagos + reembolsar", "parametros": [P_LIMITE_REEMB], "envia_mensagem": False, "reembolsa": True, "executar": _atualizar_e_reembolsar},
    "vendas_encerradas": {"rotulo": "Atualizar vendas encerradas", "parametros": [], "envia_mensagem": False, "reembolsa": False, "executar": _vendas_encerradas},
}

# Compatibilidade com o formulário e a listagem (chave -> rótulo)
ACOES_LABEL = {chave: spec["rotulo"] for chave, spec in ACOES.items()}


def exige_confirmacao(acao):
    spec = ACOES.get(acao, {})
    return bool(spec.get("envia_mensagem") or spec.get("reembolsa"))


def executar_agendamento_bruto(ag):
    """Executa um agendamento (documento do Mongo). Grava histórico e log.
    Retorna (status: 'SUCESSO'|'ERRO', mensagem)."""
    spec = ACOES.get(ag.get("acao"))
    conta = ag.get("conta")
    params = ag.get("parametros") or {}

    if not spec:
        status, mensagem = "ERRO", f"Ação '{ag.get('acao')}' não existe mais no sistema."
    else:
        try:
            ok, detalhe = spec["executar"](conta, params)
            status = "SUCESSO" if ok else "ERRO"
            mensagem = detalhe
        except ParadaSolicitada:
            raise
        except Exception as e:
            status, mensagem = "ERRO", f"Erro ao executar: {e}"

    registrar_historico(ag["_id"], ag.get("nome"), ag.get("acao"), status, mensagem)
    log_evento(conta, "sucesso" if status == "SUCESSO" else "erro",
               f"[Agendamento: {ag.get('nome')}] {mensagem}")
    return status, mensagem


def executar_agendamento_por_id(agendamento_id):
    ag = obter_agendamento_bruto(agendamento_id)
    if not ag:
        return "ERRO", "Agendamento não encontrado."
    return executar_agendamento_bruto(ag)
