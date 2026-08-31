from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, send_file

from app.db import get_connection
from app.services.rastreio import enviar_rastreio
from app.services.acao_boleto import enviar_boleto
from app.services.acao_agradecimento import enviar_agradecimento
from app.services.exportar_excel import gerar_excel_vendas

bp = Blueprint("vendas", __name__, url_prefix="/vendas")


@bp.route("/")
def index():
    conta_id = session.get("conta_ativa_id")
    conn = get_connection()
    vendas = []
    if conta_id:
        vendas = conn.execute(
            """SELECT id, order_id, produto, valor, rastreio_enviado, codigo_rastreio,
                      boleto_enviado, boleto_pago, boleto_pago_agradecimento
               FROM vendas WHERE conta_id = ? ORDER BY id DESC""",
            (conta_id,),
        ).fetchall()
    conn.close()

    return render_template("vendas/index.html", active_page="vendas", vendas=vendas)


@bp.route("/<int:venda_id>/enviar-rastreio", methods=["POST"])
def rota_enviar_rastreio(venda_id):
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("vendas.index"))

    codigo_rastreio = request.form.get("codigo_rastreio", "")
    sucesso, detalhe = enviar_rastreio(conta_id, venda_id, codigo_rastreio)

    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("vendas.index"))


@bp.route("/<int:venda_id>/enviar-boleto", methods=["POST"])
def rota_enviar_boleto(venda_id):
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("vendas.index"))

    sucesso, detalhe = enviar_boleto(conta_id, venda_id)

    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("vendas.index"))


@bp.route("/<int:venda_id>/enviar-agradecimento", methods=["POST"])
def rota_enviar_agradecimento(venda_id):
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("vendas.index"))

    data_entrega = request.form.get("data_entrega", "")
    sucesso, detalhe = enviar_agradecimento(conta_id, venda_id, data_entrega)

    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("vendas.index"))


@bp.route("/exportar")
def exportar():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("vendas.index"))

    buffer = gerar_excel_vendas(conta_id)
    nome_arquivo = f"vendas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
