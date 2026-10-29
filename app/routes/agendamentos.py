from app.routes._tarefas import disparar
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.db import (
    alternar_agendamento,
    criar_agendamento,
    listar_agendamentos,
    listar_contas,
    listar_historico,
    remover_agendamento,
)
from app.services.acoes_agendamento import ACOES, ACOES_LABEL, executar_agendamento_por_id, exige_confirmacao

bp = Blueprint("agendamentos", __name__, url_prefix="/agendamentos")


@bp.route("/")
def index():
    return render_template(
        "agendamentos/index.html",
        active_page="agendamentos",
        agendamentos=listar_agendamentos(),
        historico=listar_historico(30),
        acoes_label=ACOES_LABEL,
    )


def _ler_parametros(acao, form):
    """Lê os campos da ação escolhida. Devolve (params, erro)."""
    params = {}
    for p in ACOES[acao]["parametros"]:
        nome = p["nome"]
        if p["tipo"] == "bool":
            params[nome] = form.get(nome) == "on"
            continue
        bruto = (form.get(nome) or "").strip()
        if not bruto:
            if p["obrigatorio"]:
                return None, f"Informe: {p['rotulo']}."
            if p["padrao"] is not None:
                params[nome] = p["padrao"]
            continue
        if p["tipo"] == "inteiro":
            try:
                valor = int(bruto)
            except ValueError:
                return None, f"{p['rotulo']} deve ser um número inteiro."
            if valor < 0:
                return None, f"{p['rotulo']} não pode ser negativo."
            params[nome] = valor
        else:
            params[nome] = bruto
    if "limite" in params:
        params["limite"] = min(200, max(1, params["limite"] or 1))
    if "limite_reembolso" in params:
        params["limite_reembolso"] = min(100, max(1, params["limite_reembolso"] or 1))
    return params, None


@bp.route("/novo", methods=["GET", "POST"])
def novo():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        conta = request.form.get("conta_id", "").strip()
        tipo = request.form.get("tipo", "diaria")
        acao = request.form.get("acao")
        horarios_raw = request.form.get("horarios", "")
        data = request.form.get("data", "").strip() or None
        ativo = request.form.get("ativo") == "on"

        horarios = [h.strip() for h in horarios_raw.split(",") if h.strip()]

        if not nome or not conta or acao not in ACOES or not horarios:
            flash("Preencha nome, conta, ação e ao menos um horário válido (HH:MM).", "erro")
            return redirect(url_for("agendamentos.novo"))

        if tipo == "unica" and not data:
            flash("Informe a data para um agendamento do tipo 'única'.", "erro")
            return redirect(url_for("agendamentos.novo"))

        params, erro = _ler_parametros(acao, request.form)
        if erro:
            flash(erro, "erro")
            return redirect(url_for("agendamentos.novo"))

        if exige_confirmacao(acao) and request.form.get("confirmo") != "on":
            flash("Confirme que entende que esta ação envia mensagens ou reembolsos sem supervisão.", "erro")
            return redirect(url_for("agendamentos.novo"))

        criar_agendamento(nome, conta, tipo, acao, horarios, data, ativo, parametros=params)
        flash(f"Agendamento '{nome}' criado com sucesso.", "success")
        return redirect(url_for("agendamentos.index"))

    return render_template(
        "agendamentos/form.html",
        active_page="agendamentos",
        contas=listar_contas(),
        acoes_label=ACOES_LABEL,
        acoes_spec=ACOES,
    )


@bp.route("/<string:agendamento_id>/deletar", methods=["POST"])
def deletar(agendamento_id):
    remover_agendamento(agendamento_id)
    flash("Agendamento excluído.", "success")
    return redirect(url_for("agendamentos.index"))


@bp.route("/<string:agendamento_id>/toggle", methods=["POST"])
def toggle(agendamento_id):
    alternar_agendamento(agendamento_id)
    flash("Estado do agendamento atualizado.", "success")
    return redirect(url_for("agendamentos.index"))


@bp.route("/<string:agendamento_id>/executar-agora", methods=["POST"])
def executar_agora(agendamento_id):
    disparar("Executar agendamento", lambda c: executar_agendamento_por_id(agendamento_id))
    return redirect(url_for("dashboard.index", _anchor="log"))

