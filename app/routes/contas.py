from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, session

from app.db import get_connection

bp = Blueprint("contas", __name__, url_prefix="/contas")


@bp.route("/")
def index():
    conn = get_connection()
    contas = conn.execute(
        "SELECT id, email, nome_exibicao, ativo FROM contas ORDER BY email"
    ).fetchall()
    conn.close()
    return render_template("contas/index.html", active_page="contas", contas=contas)


@bp.route("/selecionar/<int:conta_id>")
def selecionar(conta_id):
    conn = get_connection()
    conta = conn.execute("SELECT email FROM contas WHERE id = ?", (conta_id,)).fetchone()
    conn.close()

    if not conta:
        flash("Conta não encontrada.", "erro")
        return redirect(url_for("contas.index"))

    session["conta_ativa_id"] = conta_id
    flash(f"Conta ativa alterada para {conta['email']}.", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/nova", methods=["GET", "POST"])
def nova():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        nome_exibicao = request.form.get("nome_exibicao", "").strip() or email

        if not email or "@" not in email:
            flash("Informe um e-mail válido.", "erro")
            return redirect(url_for("contas.nova"))

        conn = get_connection()
        existe = conn.execute("SELECT id FROM contas WHERE email = ?", (email,)).fetchone()
        if existe:
            conn.close()
            flash(f"O e-mail {email} já está cadastrado.", "erro")
            return redirect(url_for("contas.nova"))

        conn.execute(
            "INSERT INTO contas (email, nome_exibicao, ativo, data_criacao) VALUES (?, ?, 1, ?)",
            (email, nome_exibicao, datetime.now().strftime("%d/%m/%Y %H:%M")),
        )
        conn.commit()
        conn.close()

        flash(f"Conta {email} cadastrada com sucesso!", "success")
        return redirect(url_for("contas.index"))

    return render_template("contas/nova.html", active_page="contas")
