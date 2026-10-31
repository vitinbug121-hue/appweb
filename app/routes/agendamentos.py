from app.routes._tarefas import disparar
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.db import (
    alternar_agendamento,
    atualizar_agendamento,
    criar_agendamento,
    obter_agendamento_bruto,
    listar_agendamentos,
    listar_contas,
    listar_historico,
    remover_agendamento,
)
from app.services.controle import sinal_worker
from app.services.acoes_agendamento import ACOES, ACOES_LABEL, executar_agendamento_por_id, exige_confirmacao

bp = Blueprint("agendamentos", __name__, url_prefix="/agendamentos")


@bp.route("/")
def index():
    ultimo = sinal_worker()
    if ultimo is None:
        worker_status = {"online": False, "texto": "nunca conectou"}
    else:
        segundos = int((datetime.now() - ultimo).total_seconds())
        worker_status = {"online": segundos < 90, "texto": f"último sinal há {segundos} s"}
    return render_template(
        "agendamentos/index.html",
        worker_status=worker_status,
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


def _dados_do_formulario(form):
    """Valida o formulário de agendamento. Devolve (dados, erro)."""
    nome = form.get("nome", "").strip()
    conta = form.get("conta_id", "").strip()
    tipo = form.get("tipo", "diaria")
    acao = form.get("acao")
    horarios = [h.strip() for h in form.get("horarios", "").split(",") if h.strip()]
    data = form.get("data", "").strip() or None
    ativo = form.get("ativo") == "on"

    if not nome or not conta or acao not in ACOES or not horarios:
        return None, "Preencha nome, conta, ação e ao menos um horário válido (HH:MM)."
    if tipo == "unica" and not data:
        return None, "Informe a data para um agendamento do tipo 'única'."
    params, erro = _ler_parametros(acao, form)
    if erro:
        return None, erro
    if exige_confirmacao(acao) and form.get("confirmo") != "on":
        return None, "Confirme que entende que esta ação envia mensagens ou reembolsos sem supervisão."
    return {"nome": nome, "conta": conta, "tipo": tipo, "acao": acao, "horarios": horarios,
            "data": data, "ativo": ativo, "parametros": params}, None


@bp.route("/novo", methods=["GET", "POST"])
def novo():
    if request.method == "POST":
        dados, erro = _dados_do_formulario(request.form)
        if erro:
            flash(erro, "erro")
            return redirect(url_for("agendamentos.novo"))
        criar_agendamento(dados["nome"], dados["conta"], dados["tipo"], dados["acao"],
                          dados["horarios"], dados["data"], dados["ativo"], parametros=dados["parametros"])
        flash(f"Agendamento '{dados['nome']}' criado com sucesso.", "success")
        return redirect(url_for("agendamentos.index"))

    return render_template(
        "agendamentos/form.html",
        active_page="agendamentos",
        modo="novo",
        agendamento_id=None,
        prefill={},
        contas=listar_contas(),
        acoes_label=ACOES_LABEL,
        acoes_spec=ACOES,
    )


@bp.route("/<string:agendamento_id>/editar", methods=["GET", "POST"])
def editar(agendamento_id):
    ag = obter_agendamento_bruto(agendamento_id)
    if not ag:
        flash("Agendamento não encontrado.", "erro")
        return redirect(url_for("agendamentos.index"))

    if request.method == "POST":
        dados, erro = _dados_do_formulario(request.form)
        if erro:
            flash(erro, "erro")
            return redirect(url_for("agendamentos.editar", agendamento_id=agendamento_id))
        atualizar_agendamento(agendamento_id, dados)
        flash(f"Agendamento '{dados['nome']}' atualizado.", "success")
        return redirect(url_for("agendamentos.index"))

    prefill = {
        "nome": ag.get("nome", ""),
        "conta_id": ag.get("conta", ""),
        "tipo": ag.get("tipo", "diaria"),
        "data": ag.get("data") or "",
        "acao": ag.get("acao", ""),
        "horarios": ", ".join(ag.get("horarios") or []) if isinstance(ag.get("horarios"), list) else str(ag.get("horarios") or ""),
        "ativo": bool(ag.get("ativo", True)),
        **(ag.get("parametros") or {}),
    }
    return render_template(
        "agendamentos/form.html",
        active_page="agendamentos",
        modo="editar",
        agendamento_id=agendamento_id,
        prefill=prefill,
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

