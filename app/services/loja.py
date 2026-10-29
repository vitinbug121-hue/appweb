"""
Configurações da loja (por conta): nome da loja, valor do boleto, chave PIX,
nome e banco do recebedor PIX. Portadas das preferências do desktop.

parse_valor_br e formatar_valor_br são cópias fiéis do desktop (funções puras).
"""
from app.db import obter_config_conta, salvar_config_conta

VALOR_BOLETO_PADRAO = 138.98


def parse_valor_br(texto):
    """Converte '138,98', '1.138,98', 'R$ 138.98' em float. None se inválido ou <= 0."""
    try:
        t = str(texto or "").upper().replace("R$", "").replace(" ", "").strip()
        if not t:
            return None
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        v = float(t)
        return v if v > 0 else None
    except Exception:
        return None


def formatar_valor_br(valor):
    """138.98 -> '138,98' (sem o R$)."""
    return f"{float(valor):.2f}".replace(".", ",")


def obter_loja(conta):
    """Valores para exibir no formulário (valor do boleto com padrão do desktop)."""
    cfg = obter_config_conta(conta) if conta else {}
    valor = parse_valor_br(cfg.get("valor_boleto"))
    return {
        "nome_loja": cfg.get("nome_loja", ""),
        "valor_boleto": formatar_valor_br(valor if valor is not None else VALOR_BOLETO_PADRAO),
        "chave_pix": cfg.get("chave_pix", ""),
        "nome_recebedor_pix": cfg.get("nome_recebedor_pix", ""),
        "banco_pix": cfg.get("banco_pix", ""),
    }


def salvar_loja(conta, form):
    """Valida e grava. `form` é o request.form. Retorna (ok, mensagem)."""
    nome_loja = (form.get("nome_loja") or "").strip()
    valor_texto = (form.get("valor_boleto") or "").strip()
    valor = parse_valor_br(valor_texto)

    if not nome_loja:
        return False, "Informe o nome da loja."
    if valor is None:
        return False, "Valor do boleto inválido (ex.: 138,98)."

    salvar_config_conta(conta, {
        "nome_loja": nome_loja,
        "valor_boleto": formatar_valor_br(valor),
        "chave_pix": (form.get("chave_pix") or "").strip(),
        "nome_recebedor_pix": (form.get("nome_recebedor_pix") or "").strip(),
        "banco_pix": (form.get("banco_pix") or "").strip(),
    })
    return True, "Dados da loja salvos."
