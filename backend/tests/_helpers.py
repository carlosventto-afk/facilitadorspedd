"""
Helpers de teste compartilhados entre tests/sped, tests/excel e tests/api —
constroem um SPED mínimo e uma planilha SEFA-PA mínima que casam entre si
(mesma chave NF-e), prontos para o motor processar de ponta a ponta.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import openpyxl


def write_minimal_sped(
    tmp_path: Path,
    *,
    chave_nfe: str,
    cnpj: str,
    numero_nf: str = "1234",
    serie: str = "1",
    filename: str = "sped_entrada.txt",
) -> Path:
    """Constrói um SPED mínimo válido com 1 C100 de entrada, pronto para
    SpedParser/SpedEnricher processarem."""
    content = f"""\
|0000|EFD ICMS/IPI|PA|01062026|30062026|{cnpj}|EMPRESA TESTE|||||0|
|0001|0|
|0150|FORN001|FORNECEDOR TESTE LTDA|1058|{cnpj}||||1501|
|0990|3|
|C001|0|
|C100|0|1|FORN001|55|00|{serie}|{numero_nf}|{chave_nfe}|01062026|05062026|5000,00|0|||5000,00|0|||||||0|0||0|0|
|C190|020|2000,00|5000,00|0,00|500,00|0|0|
|C990|4|
|E001|0|
|E100|01062026|30062026|
|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|
|E990|4|
|9001|0|
|9900|0000|1|
|9900|C100|1|
|9900|C190|1|
|9900|E100|1|
|9900|E110|1|
|9900|9001|1|
|9900|9900|7|
|9900|9990|1|
|9900|9999|1|
|9990|10|
|9999|22|
"""
    path = tmp_path / filename
    path.write_text(dedent(content).lstrip(), encoding="latin-1")
    return path


def write_minimal_sefa_excel(
    tmp_path: Path,
    *,
    chave_nfe: str,
    cnpj: str,
    serie_nota: str = "1/1234",
    icms_a_pagar: float = 500.00,
    titulo: str = "Receita: 1173 - Antecipado Especial",
    filename: str = "sefa.xlsx",
) -> Path:
    """Constrói uma planilha SEFA-PA mínima (Formato B, nota a nota),
    compatível com app.excel.sefa_parser.parse_sefa_excel."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, titulo])
    ws.append([
        None, "Nº ITEM", "SERIE / NOTA", "NCM", "CNPJ",
        "VALOR NOTA FISCAL", "VALOR NOTA PRODUTO", "ICMS DO PRODUTO",
        "VALOR BASE CALC", "VALOR ICMS CALC", "ICMS A PAGAR", "BC Portaria", "DANFE",
    ])
    ws.append([
        None, "1", serie_nota, "87163900", cnpj,
        "14630", "14630", "1755.6", "14630", "2779.7", icms_a_pagar, "", chave_nfe,
    ])
    path = tmp_path / filename
    wb.save(str(path))
    return path
