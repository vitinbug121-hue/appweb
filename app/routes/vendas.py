from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, send_file

from app.db import listar_pedidos
from app.services.acao_agradecimento import enviar_agradecimento
from app.services.acao_boleto import enviar_boleto
from app.services.exportar_excel import gerar_excel_vendas
from app.services.rastreio import enviar_rastreio

bp = Blueprint("vendas", __name__, url_prefix="/vendas")

CAMPOS_LISTA = (
    "produto", "valor", "rastreio_enviado", "codigo_rastreio",
    "boleto_enviado", "boleto_pago", "boleto_pago_agradecimento",
)


def _conta_ou_erro():
    conta = session.get("conta_ativa")
    if not conta:
        flash("Selecione uma conta ativa primeiro.", "erro")
    return conta


@bp.route("/")
def index():
    conta = session.get("conta_ativa")
    vendas = []
    if conta:
        pedidos = listar_pedidos(conta)
        vendas = [
            {"order_id": oid, **{c: d.get(c) for c in CAMPOS_LISTA}}
            for oid, d in sorted(pedidos.items(), reverse=True)
        ]
    return render_template("vendas/index.html", active_page="vendas", vendas=vendas)


@bp.route("/<string:order_id>/enviar-rastreio", methods=["POST"])
def rota_enviar_rastreio(order_id):
    conta = _conta_ou_erro()
    if not conta:
        return redirect(url_for("dashboard.index", _anchor="log"))

    sucesso, detalhe = enviar_rastreio(
        conta, order_id, request.form.get("codigo_rastreio", ""), request.form.get("tipo_rastreio", "br")
    )
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/<string:order_id>/enviar-boleto", methods=["POST"])
def rota_enviar_boleto(order_id):
    conta = _conta_ou_erro()
    if not conta:
        return redirect(url_for("dashboard.index", _anchor="log"))

    sucesso, detalhe = enviar_boleto(conta, order_id)
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/<string:order_id>/enviar-agradecimento", methods=["POST"])
def rota_enviar_agradecimento(order_id):
    conta = _conta_ou_erro()
    if not conta:
        return redirect(url_for("dashboard.index", _anchor="log"))

    sucesso, detalhe = enviar_agradecimento(conta, order_id, request.form.get("data_entrega", ""))
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("dashboard.index", _anchor="log"))


@bp.route("/exportar")
def exportar():
    conta = _conta_ou_erro()
    if not conta:
        return redirect(url_for("vendas.index"))

    buffer = gerar_excel_vendas(conta)
    nome_arquivo = f"vendas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
