import json

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.db import get_connection
from app.services import agendador

bp = Blueprint("agendamentos", __name__, url_prefix="/agendamentos")


@bp.route("/")
def index():
    conn = get_connection()
    agendamentos = conn.execute(
        """SELECT a.*, c.email AS conta_email FROM agendamentos a
           JOIN contas c ON c.id = a.conta_id
           ORDER BY a.id DESC"""
    ).fetchall()
    historico = conn.execute(
        "SELECT * FROM historico_execucao ORDER BY id DESC LIMIT 30"
    ).fetchall()
    conn.close()

    return render_template(
        "agendamentos/index.html",
        active_page="agendamentos",
        agendamentos=agendamentos,
        historico=historico,
        acoes_label=agendador.ACOES_LABEL,
    )


@bp.route("/novo", methods=["GET", "POST"])
def novo():
    conn = get_connection()
    contas = conn.execute("SELECT id, email FROM contas WHERE ativo = 1 ORDER BY email").fetchall()
    conn.close()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        conta_id = request.form.get("conta_id")
        tipo = request.form.get("tipo", "diaria")
        acao = request.form.get("acao")
        horarios_raw = request.form.get("horarios", "")
        data = request.form.get("data", "").strip() or None
        ativo = 1 if request.form.get("ativo") == "on" else 0

        horarios = [h.strip() for h in horarios_raw.split(",") if h.strip()]

        if not nome or not conta_id or acao not in agendador.ACOES_LABEL or not horarios:
            flash("Preencha nome, conta, ação e ao menos um horário válido (HH:MM).", "erro")
            return redirect(url_for("agendamentos.novo"))

        if tipo == "unica" and not data:
            flash("Informe a data para um agendamento do tipo 'única'.", "erro")
            return redirect(url_for("agendamentos.novo"))

        conn = get_connection()
        conn.execute(
            """INSERT INTO agendamentos (nome, conta_id, tipo, acao, horarios, data, ativo, intervalo_minutos)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (nome, conta_id, tipo, acao, json.dumps(horarios), data, ativo),
        )
        conn.commit()
        conn.close()

        flash(f"Agendamento '{nome}' criado com sucesso.", "success")
        return redirect(url_for("agendamentos.index"))

    return render_template(
        "agendamentos/form.html",
        active_page="agendamentos",
        contas=contas,
        acoes_label=agendador.ACOES_LABEL,
    )


@bp.route("/<int:agendamento_id>/deletar", methods=["POST"])
def deletar(agendamento_id):
    conn = get_connection()
    conn.execute("DELETE FROM agendamentos WHERE id = ?", (agendamento_id,))
    conn.commit()
    conn.close()
    flash("Agendamento excluído.", "success")
    return redirect(url_for("agendamentos.index"))


@bp.route("/<int:agendamento_id>/toggle", methods=["POST"])
def toggle(agendamento_id):
    conn = get_connection()
    ag = conn.execute("SELECT ativo FROM agendamentos WHERE id = ?", (agendamento_id,)).fetchone()
    if ag:
        novo_estado = 0 if ag["ativo"] else 1
        conn.execute("UPDATE agendamentos SET ativo = ? WHERE id = ?", (novo_estado, agendamento_id))
        conn.commit()
    conn.close()
    flash("Estado do agendamento atualizado.", "success")
    return redirect(url_for("agendamentos.index"))


@bp.route("/<int:agendamento_id>/executar-agora", methods=["POST"])
def executar_agora(agendamento_id):
    status, mensagem = agendador.executar_agendamento(agendamento_id)
    flash(mensagem, "success" if status == "SUCESSO" else "erro")
    return redirect(url_for("agendamentos.index"))
