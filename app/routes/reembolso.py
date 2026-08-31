from flask import Blueprint, render_template, redirect, url_for, flash, session

from app.db import get_connection
from app.services import mercadopago

bp = Blueprint("reembolso", __name__, url_prefix="/reembolso")


@bp.route("/")
def index():
    conta_id = session.get("conta_ativa_id")
    conn = get_connection()
    vendas = []
    if conta_id:
        vendas = conn.execute(
            """SELECT id, order_id, produto, valor, id_payment, data_boleto_pago
               FROM vendas
               WHERE conta_id = ? AND boleto_pago = 1 AND rembolsado = 0 AND id_payment IS NOT NULL
               ORDER BY id DESC""",
            (conta_id,),
        ).fetchall()
    conn.close()

    tokens_cadastrados = len(mercadopago.obter_tokens_reembolso())

    return render_template(
        "reembolso/index.html",
        active_page="reembolso",
        vendas=vendas,
        tokens_cadastrados=tokens_cadastrados,
    )


@bp.route("/<int:venda_id>/reembolsar", methods=["POST"])
def reembolsar(venda_id):
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("reembolso.index"))

    sucesso, detalhe = mercadopago.reembolsar_venda(conta_id, venda_id)
    flash(detalhe, "success" if sucesso else "erro")
    return redirect(url_for("reembolso.index"))


@bp.route("/reembolsar-todos", methods=["POST"])
def reembolsar_todos():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("reembolso.index"))

    conn = get_connection()
    ids = [
        row["id"]
        for row in conn.execute(
            """SELECT id FROM vendas
               WHERE conta_id = ? AND boleto_pago = 1 AND rembolsado = 0 AND id_payment IS NOT NULL""",
            (conta_id,),
        ).fetchall()
    ]
    conn.close()

    sucesso_count = 0
    for venda_id in ids:
        sucesso, _ = mercadopago.reembolsar_venda(conta_id, venda_id)
        if sucesso:
            sucesso_count += 1

    flash(f"Reembolso em lote concluído: {sucesso_count} de {len(ids)} venda(s) reembolsada(s).",
          "success" if sucesso_count == len(ids) else "erro")
    return redirect(url_for("reembolso.index"))
