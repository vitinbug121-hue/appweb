from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.auth import proximo_seguro, usuario_logado
from app.db import obter_usuario

bp = Blueprint("auth", __name__, url_prefix="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if usuario_logado() and request.method == "GET":
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip().lower()
        senha = request.form.get("senha", "")
        registro = obter_usuario(usuario)

        if registro and check_password_hash(registro.get("senha_hash", ""), senha):
            session.clear()
            session["usuario"] = usuario
            destino = proximo_seguro(request.args.get("next")) or url_for("dashboard.index")
            return redirect(destino)

        flash("Usuário ou senha inválidos.", "erro")
        return redirect(url_for("auth.login", next=request.args.get("next", "")))

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Você saiu do sistema.", "success")
    return redirect(url_for("auth.login"))
