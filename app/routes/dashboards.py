from datetime import datetime

from flask import Blueprint, render_template, request, session

from app.services import dashboards

bp = Blueprint("dashboards", __name__, url_prefix="/dashboards")


def _data_html(texto):
    """Campo <input type=date> envia AAAA-MM-DD."""
    try:
        return datetime.strptime(texto, "%Y-%m-%d") if texto else None
    except ValueError:
        return None


@bp.route("/vendas")
def vendas():
    conta = session.get("conta_ativa")
    dados = dashboards.dashboard_vendas(conta) if conta else {"barras": [], "total": 0}
    return render_template("dashboards/vendas.html", active_page="dashboards", d=dados)


@bp.route("/boletos-pagos")
def boletos_pagos():
    contas_sel = request.args.getlist("contas")
    de = _data_html(request.args.get("de", ""))
    ate = _data_html(request.args.get("ate", ""))
    dados = dashboards.dashboard_boletos_pagos(contas_sel or None, de, ate)
    return render_template(
        "dashboards/boletos_pagos.html",
        active_page="dashboards",
        d=dados,
        contas=dashboards.todas_as_contas(),
        contas_sel=contas_sel,
        de=request.args.get("de", ""),
        ate=request.args.get("ate", ""),
    )


@bp.route("/lotes")
def lotes():
    conta = session.get("conta_ativa")
    termo = request.args.get("filtro", "")
    lotes_lista = dashboards.dashboard_lotes(conta, termo) if conta else []
    return render_template("dashboards/lotes.html", active_page="dashboards", lotes=lotes_lista, filtro=termo)
