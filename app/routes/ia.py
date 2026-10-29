from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.db import obter_config_conta, obter_script_ia, salvar_script_ia
from app.routes._tarefas import disparar
from app.services import autorizacao, ia_conversa, ia_duvidas

bp = Blueprint("ia", __name__, url_prefix="/ia")

# Situações da venda usadas no teste (nomes = campos do pedido)
FLAGS = [
    ("solicitado", "Solicitado (1ª mensagem enviada)"),
    ("rastreio_enviado", "Rastreio enviado"),
    ("boleto_autorizado_msg", "Taxado (autorização enviada)"),
    ("cliente_autorizou", "Cliente autorizou"),
    ("boleto_enviado", "Boleto enviado"),
    ("boleto_pago", "Boleto pago"),
    ("pago_via_pix", "PIX pago"),
    ("cobrado_via_pix", "Cobrado via PIX"),
    ("cobrado_dobro", "Cobrado em dobro"),
    ("boleto_pago_dobro", "Dobro pago"),
    ("encerrada", "Venda encerrada"),
    ("tem_reclamacao", "Tem reclamação aberta"),
]
ETAPAS = ["Solicitado", "Rastreio enviado", "Taxado", "Boleto enviado",
          "PIX cobrado", "Pago", "Dobro cobrado", "Encerrada"]


def _contexto(teste=None, form=None):
    conta = session.get("conta_ativa")
    return dict(
        active_page="ia",
        script_comum=obter_script_ia(conta, "script_comum") if conta else None,
        script_question=obter_script_ia(conta, "script_question") if conta else None,
        lotes=autorizacao.calcular_lotes(conta) if conta else [],
        flags=FLAGS,
        etapas=ETAPAS,
        teste=teste,
        form=form,
    )


@bp.route("/", methods=["GET"])
def index():
    return render_template("ia/index.html", **_contexto())


@bp.route("/salvar-script-comum", methods=["POST"])
def salvar_script_comum():
    texto = request.form.get("script_comum", "").strip()
    if not texto:
        flash("O script IA comum não pode ficar vazio.", "erro")
    else:
        salvar_script_ia(None, "script_comum", texto)
        flash("IA comum salva (vale para todas as contas).", "success")
    return redirect(url_for("ia.index"))


@bp.route("/salvar-script", methods=["POST"])
def salvar_script():
    texto = request.form.get("script_question", "").strip()
    if not texto:
        flash("O script IA question não pode ficar vazio.", "erro")
    else:
        salvar_script_ia(None, "script_question", texto)
        flash("IA question salva (vale para todas as contas).", "success")
    return redirect(url_for("ia.index"))


@bp.route("/responder-duvidas", methods=["POST"])
def responder_duvidas():
    disparar("IA de dúvidas", ia_duvidas.responder_duvidas_pendentes)
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/responder-conversas", methods=["POST"])
def responder_conversas():
    try:
        limite = min(200, max(1, int(request.form.get("limite", "20") or 20)))
        lote = request.form.get("lote", "").strip()
        lote = int(lote) if lote else None
    except ValueError:
        flash("Quantidade e lote devem ser números inteiros.", "erro")
        return redirect(url_for("ia.index"))
    disparar(
        "IA de conversas", ia_conversa.responder_lote,
        limite=limite, lote=lote,
        excluir_pix=request.form.get("excluir_pix") == "on",
        somente_nao_taxados=request.form.get("somente_nao_taxados") == "on",
    )
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/testar", methods=["POST"])
def testar():
    conta = session.get("conta_ativa")
    texto = request.form.get("mensagem", "").strip()
    if not texto:
        flash("Digite a mensagem do cliente para testar.", "erro")
        return redirect(url_for("ia.index"))
    script = (obter_script_ia(conta, "script_comum") or "").strip() if conta else ""
    if not script:
        flash("Salve a IA comum antes de testar.", "erro")
        return redirect(url_for("ia.index"))

    dados = {chave: True for chave, _ in FLAGS if request.form.get(chave) == "on" and chave != "tem_reclamacao"}
    for campo in ("metodo_taxa", "provedor_taxa", "tipo_rastreio"):
        valor = request.form.get(campo, "").strip()
        if valor:
            dados[campo] = valor
    tem_reclamacao = request.form.get("tem_reclamacao") == "on"
    nome_loja = (obter_config_conta(conta).get("nome_loja") or "").strip()

    resultado = ia_conversa.testar(script, texto, dados, tem_reclamacao, nome_loja)
    resultado["etapa"] = request.form.get("etapa", "")
    return render_template("ia/index.html", **_contexto(teste=resultado, form=request.form))
