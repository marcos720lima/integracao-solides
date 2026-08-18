"""Gera a planilha Excel de desligamentos (usada pelo botão "Exportar Excel" do gráfico)."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from painel.utils import filtrar_historico_por_periodo

COLUNAS = ["Data do desligamento", "Setor", "Colaborador", "Cargo"]


def gerar_planilha_desligamentos(historico, inicio=None, fim=None):
    """
    Monta um .xlsx (em memória) com uma linha por colaborador desligado no
    período informado, colunas: Data do desligamento, Setor, Colaborador, Cargo.
    Retorna um BytesIO pronto pra ser enviado como download.
    """
    linhas = filtrar_historico_por_periodo(historico, inicio, fim)
    # Mais organizado pra leitura em planilha: agrupado por setor, e por data dentro do setor
    linhas.sort(key=lambda linha: (
        (linha.get("setor") or "").strip() or "Não informado",
        linha.get("data_registro") or "",
    ))

    workbook = Workbook()
    aba = workbook.active
    aba.title = "Desligamentos por setor"

    aba.append(COLUNAS)
    fonte_cabecalho = Font(name="Arial", bold=True, color="FFFFFF")
    preenchimento_cabecalho = PatternFill(start_color="00995D", end_color="00995D", fill_type="solid")
    for celula in aba[1]:
        celula.font = fonte_cabecalho
        celula.fill = preenchimento_cabecalho
        celula.alignment = Alignment(vertical="center")

    for linha in linhas:
        aba.append([
            linha.get("data_desligamento") or "",
            (linha.get("setor") or "").strip() or "Não informado",
            linha.get("nome_colaborador") or "",
            linha.get("cargo") or "",
        ])

    for celula in aba["A"][1:]:
        celula.font = Font(name="Arial")
    for coluna in ["B", "C", "D"]:
        for celula in aba[coluna][1:]:
            celula.font = Font(name="Arial")

    larguras = [20, 26, 32, 26]
    for indice, largura in enumerate(larguras, start=1):
        aba.column_dimensions[get_column_letter(indice)].width = largura

    aba.freeze_panes = "A2"
    aba.auto_filter.ref = f"A1:D{aba.max_row}"

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
