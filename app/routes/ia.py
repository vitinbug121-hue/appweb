from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services import ia_duvidas

bp = Blueprint("ia", __name__, url_prefix="/ia")


@bp.route("/")
def index():
    conta_id = session.get("conta_ativa_id")
    script_atual = ia_duvidas.obter_script(conta_id, "script_question") if conta_id else None
    return render_template("ia/index.html", active_page="ia", script_atual=script_atual)


@bp.route("/salvar-script", methods=["POST"])
def salvar_script():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("ia.index"))

    texto = request.form.get("script_question", "").strip()
    if not texto:
        flash("O script não pode ficar vazio.", "erro")
        return redirect(url_for("ia.index"))

    ia_duvidas.salvar_script(conta_id, "script_question", texto)
    flash("Script da IA salvo com sucesso.", "success")
    return redirect(url_for("ia.index"))


@bp.route("/responder-duvidas", methods=["POST"])
def responder_duvidas():
    conta_id = session.get("conta_ativa_id")
    if not conta_id:
        flash("Selecione uma conta ativa primeiro.", "erro")
        return redirect(url_for("ia.index"))

    resumo = ia_duvidas.responder_duvidas_pendentes(conta_id)
    flash(
        f"IA Dúvidas concluída — respondidas: {resumo['respondidas']}, "
        f"puladas: {resumo['puladas']}, erros: {resumo['erros']}.",
        "success" if resumo["erros"] == 0 else "erro",
    )
    return redirect(url_for("ia.index"))
