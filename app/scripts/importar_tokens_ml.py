"""
Importa a autorização do Mercado Livre a partir de arquivos JSON do seu disco.
Os valores NÃO são digitados nem colados: o script lê os arquivos e grava no
banco já cifrados com TOKEN_ENCRYPTION_KEY.

Uso (dentro de appweb):

  python -m app.scripts.importar_tokens_ml --conta EMAIL ^
      --tokens "C:\\caminho\\ml_tokens_autorizacao.json" ^
      --config "C:\\caminho\\config_conta.json"            (opcional)

Sem --executar, só mostra o que seria gravado (sem valores secretos).
Com --executar, grava de verdade.

Campos lidos:
  ml_tokens_autorizacao.json: access_token, refresh_token, expires_in, user_id
  config_conta.json:          ML_CLIENT_ID, ML_CLIENT_SECRET, ML_SELLER_ID
"""
import argparse
import json
import os
import sys

from app.env import carregar_env

carregar_env()


def _ler_json(caminho):
    with open(caminho, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    from app.db import (
        conta_existe,
        criar_conta,
        salvar_config_conta,
        salvar_tokens_ml,
    )

    ap = argparse.ArgumentParser()
    ap.add_argument("--conta", required=True, help="e-mail da conta (chave no sistema)")
    ap.add_argument("--tokens", required=True, help="caminho do ml_tokens_autorizacao.json")
    ap.add_argument("--config", help="caminho do config_conta.json (opcional)")
    ap.add_argument("--executar", action="store_true", help="grava de verdade")
    args = ap.parse_args()

    if not os.path.isfile(args.tokens):
        sys.exit(f"Arquivo não encontrado: {args.tokens}")
    tokens = _ler_json(args.tokens)
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("O arquivo de tokens não tem refresh_token.")

    config = {}
    if args.config:
        if not os.path.isfile(args.config):
            sys.exit(f"Arquivo não encontrado: {args.config}")
        config = _ler_json(args.config)

    seller = config.get("ML_SELLER_ID") or tokens.get("user_id")
    campos_config = {
        "ml_client_id": config.get("ML_CLIENT_ID"),
        "ml_client_secret": config.get("ML_CLIENT_SECRET"),
        "ml_seller_id": str(seller) if seller else None,
    }
    campos_config = {k: v for k, v in campos_config.items() if v}

    print(f"Conta: {args.conta}")
    print(f"Tokens: refresh_token presente, access_token {'presente' if access else 'ausente'}, "
          f"expires_in={tokens.get('expires_in')}")
    print(f"Configuração a gravar: {', '.join(campos_config) or 'nada'} (valores ocultos)")

    if not args.executar:
        print("\nSIMULAÇÃO: nada foi gravado. Rode de novo com --executar para gravar.")
        return

    if not conta_existe(args.conta):
        criar_conta(args.conta, args.conta)
        print("Conta criada no sistema.")
    if campos_config:
        salvar_config_conta(args.conta, campos_config)
    salvar_tokens_ml(args.conta, access, refresh, str(tokens.get("expires_in", "")))
    print("Gravado com sucesso (valores cifrados).")
    print("Apague os arquivos JSON do disco depois de conferir a tela de autorização.")


if __name__ == "__main__":
    main()
