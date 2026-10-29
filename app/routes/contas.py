from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from pymongo.errors import DuplicateKeyError

from app.db import conta_existe, criar_conta, listar_contas

bp = Blueprint("contas", __name__, url_prefix="/contas")


@bp.route("/")
def index():
    return render_template("contas/index.html", active_page="contas", contas=listar_contas())


@bp.route("/selecionar/<string:conta>")
def selecionar(conta):
    if not conta_existe(conta):
        flash("Conta não encontrada.", "erro")
        return redirect(url_for("contas.index"))

    session["conta_ativa"] = conta
    flash(f"Conta ativa alterada para {conta}.", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/nova", methods=["GET", "POST"])
def nova():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nome_exibicao = request.form.get("nome_exibicao", "").strip() or email

        if not email or "@" not in email:
            flash("Informe um e-mail válido.", "erro")
            return redirect(url_for("contas.nova"))

        if conta_existe(email):
            flash(f"O e-mail {email} já está cadastrado.", "erro")
            return redirect(url_for("contas.nova"))

        try:
            criar_conta(email, nome_exibicao)
        except DuplicateKeyError:
            flash(f"O e-mail {email} já está cadastrado.", "erro")
            return redirect(url_for("contas.nova"))

        flash(f"Conta {email} cadastrada com sucesso!", "success")
        return redirect(url_for("contas.index"))

    return render_template("contas/nova.html", active_page="contas")
