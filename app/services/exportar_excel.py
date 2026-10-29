"""
Exportação de vendas para Excel (portada de `exportar_para_excel` do desktop).
Gera em memória (BytesIO). Link clicável para o Mercado Livre em cada Order ID;
linha inteira destacada em vermelho quando a venda está encerrada.
"""
import io

import pandas as pd

from app.db import listar_pedidos

COLUNAS = [
    "Order ID", "Status", "Produto", "Data", "Rastreio", "Cor Produto", "Valor",
    "Numero", "Boleto Enviado", "Id Payment", "Boleto Pago", "Boleto Vencido",
    "Horario Boleto", "Encerrada", "Data Boleto",
]

BASE_URL_ML = "https://www.mercadolivre.com.br/vendas/{}/detalhe#source=excel"


def _sim_nao(valor):
    return "Sim" if valor else "Não"


def _linha_para_dict(order_id, d):
    if d.get("boleto_enviado"):
        status = "Etapa 3"
    elif d.get("rastreio_enviado"):
        status = "Etapa 2"
    else:
        status = "Etapa 1"

    return {
        "Order ID": order_id,
        "Status": status,
        "Produto": d.get("produto") or "N/A",
        "Data": d.get("data_solicitacao_inicial") or "N/A",
        "Rastreio": d.get("codigo_rastreio") or "Pendente",
        "Cor Produto": d.get("corProduto") or "N/A",
        "Valor": d.get("valor") or "N/A",
        "Numero": d.get("zap_extraido") or "N/A",
        "Boleto Enviado": d.get("codigo_boleto") or "N/A",
        "Id Payment": d.get("id_payment") or "N/A",
        "Boleto Pago": _sim_nao(d.get("boleto_pago") or d.get("pago_via_pix")),
        "Boleto Vencido": _sim_nao(d.get("boleto_vencido")),
        "Horario Boleto": d.get("horario_boleto") or "N/A",
        "Encerrada": _sim_nao(d.get("encerrada")),
        "Data Boleto": d.get("data_boleto") or "N/A",
    }


def gerar_excel_vendas(conta):
    """Retorna um BytesIO já posicionado no início, pronto pra `send_file`."""
    pedidos = listar_pedidos(conta)
    linhas = [_linha_para_dict(oid, d) for oid, d in sorted(pedidos.items())]
    df = pd.DataFrame(linhas, columns=COLUNAS)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Vendas")
        workbook = writer.book
        worksheet = writer.sheets["Vendas"]

        format_link = workbook.add_format({"font_color": "blue", "underline": 1})
        format_vermelho = workbook.add_format({"bg_color": "#FFC7CE"})
        format_link_vermelho = workbook.add_format(
            {"font_color": "blue", "underline": 1, "bg_color": "#FFC7CE"}
        )

        col_idx_id = COLUNAS.index("Order ID")

        for row_num, row_data in df.iterrows():
            excel_row = row_num + 1  # +1 pula o cabeçalho
            order_id = row_data["Order ID"]
            url = BASE_URL_ML.format(order_id)
            encerrada = row_data["Encerrada"] == "Sim"

            if encerrada:
                for col_num, col_nome in enumerate(COLUNAS):
                    if col_num == col_idx_id:
                        worksheet.write_url(excel_row, col_num, url, string=str(order_id), cell_format=format_link_vermelho)
                    else:
                        worksheet.write(excel_row, col_num, row_data[col_nome], format_vermelho)
            else:
                worksheet.write_url(excel_row, col_idx_id, url, string=str(order_id), cell_format=format_link)

        for i, col in enumerate(COLUNAS):
            worksheet.set_column(i, i, max(12, len(col) + 2))

    buffer.seek(0)
    return buffer
