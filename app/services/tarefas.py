"""
Execução em segundo plano. A rota responde na hora e a ação roda numa thread,
registrando início, fim, interrupção e erros no log (que aparece no dashboard).
"""
import threading

from app.services.controle import ParadaSolicitada
from app.services.logger import log_evento


def iniciar(conta, nome, funcao, *args, **kwargs):
    def alvo():
        log_evento(conta, "info", f"{nome}: iniciado.")
        try:
            resultado = funcao(conta, *args, **kwargs)
        except ParadaSolicitada:
            log_evento(conta, "erro", f"{nome}: interrompido pela parada de emergência.")
            return
        except Exception as e:
            log_evento(conta, "erro", f"{nome}: erro inesperado — {e}")
            return
        if isinstance(resultado, dict) and resultado.get("erro"):
            log_evento(conta, "erro", f"{nome}: {resultado['erro']}")
            return
        log_evento(conta, "info", f"{nome}: terminado.")

    threading.Thread(target=alvo, daemon=True, name=f"tarefa-{nome}").start()
