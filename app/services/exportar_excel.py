"""
Portado de `exportar_para_excel` do sistema desktop original: gera uma
planilha com todas as vendas da conta, com link clicável pro Mercado
Livre em cada Order ID e a linha inteira destacada em vermelho quando a
venda está encerrada. Diferença: aqui não salva em disco — gera em
memória (BytesIO) e devolve pro navegador baixar direto (`send_file`).
"""
import io

import pandas as pd

from app.db import get_connection

COLUNAS = [
    "Order ID", "Status", "Produto", "Data", "Rastreio", "Cor Produto", "Valor",
    "Numero", "Boleto Enviado", "Id Payment", "Boleto Pago", "Boleto Vencido",
    "Horario Boleto", "Encerrada", "Data Boleto",
]

BASE_URL_ML = "https://www.mercadolivre.com.br/vendas/{}/detalhe#source=excel"


def _linha_para_dict(v):
    if v["boleto_enviado"]:
        status = "Etapa 3"
    elif v["rastreio_enviado"]:
        status = "Etapa 2"
    else:
        status = "Etapa 1"

    return {
        "Order ID": v["order_id"],
        "Status": status,
        "Produto": v["produto"] or "N/A",
        "Data": v["data_solicitacao_inicial"] or "N/A",
        "Rastreio": v["codigo_rastreio"] or "Pendente",
        "Cor Produto": v["cor_produto"] or "N/A",
        "Valor": v["valor"] or "N/A",
        "Numero": v["zap_extraido"] or "N/A",
        "Boleto Enviado": v["codigo_boleto"] or "N/A",
        "Id Payment": v["id_payment"] or "N/A",
        "Boleto Pago": "Sim" if v["boleto_pago"] else "Não",
        "Boleto Vencido": "Sim" if v["boleto_vencido"] else "Não",
        "Horario Boleto": v["horario_boleto"] or "N/A",
        "Encerrada": "Sim" if v["encerrada"] else "Não",
        "Data Boleto": v["data_boleto"] or "N/A",
    }


def gerar_excel_vendas(conta_id):
    """Retorna um BytesIO já posicionado no início, pronto pra `send_file`."""
    conn = get_connection()
    vendas = conn.execute(
        "SELECT * FROM vendas WHERE conta_id = ? ORDER BY id", (conta_id,)
    ).fetchall()
    conn.close()

    df = pd.DataFrame([_linha_para_dict(v) for v in vendas], columns=COLUNAS)

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
