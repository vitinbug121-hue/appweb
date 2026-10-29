"""
Login do sistema. Qualquer rota exige usuário logado, exceto a tela de login
e os arquivos estáticos.

Sessão: o cookie é de sessão (sem data de expiração). Ele vale até o navegador
ser fechado (ou a máquina reiniciar). Não é marcado como permanente.
"""
from urllib.parse import urlparse

from flask import redirect, request, session, url_for

ENDPOINTS_PUBLICOS = {"auth.login", "static"}


def usuario_logado():
    return session.get("usuario")


def proximo_seguro(destino):
    """Aceita só caminhos internos (evita redirecionar para outro site)."""
    if not destino:
        return None
    p = urlparse(destino)
    if p.scheme or p.netloc or not destino.startswith("/") or destino.startswith("//"):
        return None
    return destino


def exigir_login():
    """Retorna um redirect para o login quando não há usuário logado; None se pode seguir."""
    if request.endpoint in ENDPOINTS_PUBLICOS or request.endpoint is None:
        return None
    if usuario_logado():
        return None
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
