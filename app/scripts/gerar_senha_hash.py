"""
Gera o hash da senha de um usuário, para você colar no banco.

    python -m app.scripts.gerar_senha_hash

Digite a senha (não aparece na tela). O programa imprime o hash e um exemplo
de inserção no MongoDB. A senha em texto puro nunca é gravada.
"""
import getpass

from werkzeug.security import generate_password_hash


def main():
    usuario = input("Nome de usuário (minúsculo, sem espaços): ").strip().lower()
    if not usuario or " " in usuario:
        raise SystemExit("Nome de usuário inválido.")
    senha = getpass.getpass("Senha: ")
    if len(senha) < 8:
        raise SystemExit("Use pelo menos 8 caracteres.")
    if senha != getpass.getpass("Repita a senha: "):
        raise SystemExit("As senhas não conferem.")

    hash_ = generate_password_hash(senha)
    print("\nHash gerado:\n" + hash_)
    print("\nNo MongoDB (coleção 'usuarios'), insira:")
    print('db.usuarios.insertOne({ usuario: "%s", senha_hash: "%s", ativo: true })' % (usuario, hash_))


if __name__ == "__main__":
    main()
