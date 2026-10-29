"""
Asaas via navegador (Selenium), como no desktop: abre a página da cobrança e lê
o campo "Situação". Exige Chrome e chromedriver no servidor.

Sessão de login: fica no perfil dedicado ASAAS_PERFIL_CHROME. Para logar,
rode uma vez:  python -m app.scripts.asaas_login  (abre o Chrome visível).
Se a sessão expirar, a execução para com mensagem para repetir o login.

Variáveis (.env):
    ASAAS_PERFIL_CHROME   pasta do perfil do Chrome (obrigatória)
    CHROMEDRIVER_PATH     caminho do chromedriver (opcional; senão, Selenium Manager)
    CHROME_BINARY         caminho do Chrome/Chromium (opcional)
    ASAAS_HEADLESS        1 = sem janela (padrão), 0 = com janela

Não rodar o login e esta atualização ao mesmo tempo com o mesmo perfil:
o Chrome bloqueia o perfil enquanto estiver aberto.
"""
import os

from app.db import agora_texto, atualizar_campos_pedido, listar_pedidos
from app.services import asaas
from app.services.logger import log_evento
from app.services.controle import verificar_parada

URL_LOGIN = "https://www.asaas.com/login/auth"
URL_COBRANCA = "https://www.asaas.com/payment/show/{payment_id}"
XPATH_SITUACAO = (
    "/html/body/atlas-screen/atlas-page/atlas-page-content/div/div[2]/div[2]/div/div[1]/div[2]"
    "/form/div[2]/div[1]/div[1]/div[1]/div/span"
)
CSS_SITUACAO = "span.icarus-status-info"
TIMEOUT = 20
PAUSA = 1


class LoginNecessario(RuntimeError):
    pass


def _perfil():
    perfil = os.environ.get("ASAAS_PERFIL_CHROME", "").strip()
    if not perfil:
        raise RuntimeError("ASAAS_PERFIL_CHROME não configurado no .env.")
    return perfil


def abrir_driver(headless=None):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opcoes = Options()
    opcoes.add_argument(f"--user-data-dir={_perfil()}")
    if headless is None:
        headless = os.environ.get("ASAAS_HEADLESS", "1").strip() != "0"
    if headless:
        opcoes.add_argument("--headless=new")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    binario = os.environ.get("CHROME_BINARY", "").strip()
    if binario:
        opcoes.binary_location = binario

    caminho = os.environ.get("CHROMEDRIVER_PATH", "").strip()
    servico = Service(executable_path=caminho) if caminho else Service()
    return webdriver.Chrome(service=servico, options=opcoes)


def ler_situacao(driver, payment_id):
    verificar_parada()
    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(URL_COBRANCA.format(payment_id=payment_id))
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    if "login" in driver.current_url.lower():
        raise LoginNecessario("A sessão do Asaas expirou.")

    def _procurar(d):
        if "login" in d.current_url.lower():
            return "__LOGIN__"
        for by, seletor in ((By.XPATH, XPATH_SITUACAO), (By.CSS_SELECTOR, CSS_SITUACAO)):
            try:
                texto = (d.find_element(by, seletor).get_attribute("textContent") or "").strip()
                if texto:
                    return texto
            except NoSuchElementException:
                continue
        return False

    texto = WebDriverWait(driver, TIMEOUT).until(_procurar)
    if texto == "__LOGIN__":
        raise LoginNecessario("A sessão do Asaas expirou.")
    return texto


def atualizar_asaas_navegador(conta):
    """Opção navegador. Mesmas regras da opção API."""
    try:
        _perfil()
    except RuntimeError as e:
        log_evento(conta, "erro", str(e))
        return {"erro": str(e)}

    pedidos = listar_pedidos(conta)
    normais = asaas.candidatos_normal(pedidos)
    dobros = asaas.candidatos_dobro(pedidos)
    resumo = {"verificados": len(normais) + len(dobros), "pagos": 0, "erros": 0}
    if not resumo["verificados"]:
        log_evento(conta, "info", "Asaas (navegador): nenhum boleto pendente para consultar.")
        return resumo

    try:
        driver = abrir_driver()
    except Exception as e:
        log_evento(conta, "erro", f"Não foi possível abrir o Chrome para o Asaas: {e}")
        return {"erro": f"Não foi possível abrir o Chrome: {e}"}

    try:
        alvos = (
            [(o, "id_payment", "boleto_pago", "data_boleto_pago") for o in normais]
            + [(o, "id_payment_dobro", "boleto_pago_dobro", "data_boleto_pago_dobro") for o in dobros]
        )
        for oid, campo_id, campo_pago, campo_data in alvos:
            payment_id = str(pedidos[oid][campo_id]).strip()
            try:
                situacao = ler_situacao(driver, payment_id)
            except LoginNecessario:
                raise
            except Exception as e:
                resumo["erros"] += 1
                log_evento(conta, "erro", f"Ordem {oid}: erro ao ler o Asaas ({payment_id}) — {e}")
                continue

            if asaas.situacao_paga(situacao):
                atualizar_campos_pedido(conta, oid, {campo_pago: True, campo_data: agora_texto()})
                resumo["pagos"] += 1
                log_evento(conta, "sucesso", f"Ordem {oid}: marcado como pago (Asaas: {situacao}).")
            else:
                log_evento(conta, "info", f"Ordem {oid}: Asaas situação '{situacao}'.")
            import time
            time.sleep(PAUSA)
    except LoginNecessario:
        msg = "Sessão do Asaas expirou. Rode: python -m app.scripts.asaas_login e tente de novo."
        log_evento(conta, "erro", msg)
        return {"erro": msg, **{k: v for k, v in resumo.items()}}
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    log_evento(conta, "sucesso",
               f"Asaas (navegador) finalizado. Verificados: {resumo['verificados']} | "
               f"Pagos: {resumo['pagos']} | Erros: {resumo['erros']}")
    return resumo
