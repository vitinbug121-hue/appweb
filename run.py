from app import create_app

app = create_app()

if __name__ == "__main__":
    # threaded=True é necessário porque o log em tempo real (SSE, em
    # app/routes/logs.py) mantém uma conexão HTTP aberta por aba do
    # navegador — sem isso, o servidor de desenvolvimento travaria
    # depois da primeira aba aberta.
    app.run(debug=True, host="127.0.0.1", port=5000, threaded=True)
