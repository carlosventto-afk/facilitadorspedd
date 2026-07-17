"""Testes unitários para SpedParser (Pass 1 — indexação)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest

from app.sped.parser import SpedParser


# ── Fixtures ─────────────────────────────────────────────────────────────────

CHAVE_NF = "15250112345678000199550010000012340000000010"
CHAVE_NF_2 = "15250112345678000199550010000056780000000020"


def _write_sped(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.txt"
    p.write_text(dedent(content).lstrip(), encoding="latin-1")
    return p


MINIMAL_SPED = """\
|0000|EFD ICMS/IPI|PA|15012025|31012025|12345678000199|EMPRESA TESTE|||||0|
|0001|0|
|0150|FORN001|FORNECEDOR TESTE LTDA|1058|12345678000199||||1501|
|0990|3|
|C001|0|
|C100|0|1|FORN001|55|00|1|1234|{chave}|01012025|05012025|5000,00|0|||5000,00|0|||||||0|0||0|0|
|C190|020|2000,00|5000,00|0,00|500,00|0|0|
|C990|4|
|E001|0|
|E100|01012025|31012025|
|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|
|E990|4|
|9001|0|
|9900|0000|1|
|9900|C001|1|
|9900|C100|1|
|9900|C190|1|
|9900|C990|1|
|9900|E001|1|
|9900|E100|1|
|9900|E110|1|
|9900|E990|1|
|9900|9001|1|
|9900|9900|11|
|9900|9990|1|
|9900|9999|1|
|9990|13|
|9999|27|
""".format(chave=CHAVE_NF)


def test_parse_minimal(tmp_path: Path) -> None:
    path = _write_sped(tmp_path, MINIMAL_SPED)
    index = SpedParser().parse(path)

    assert len(index.c100_blocks) == 1
    block = index.c100_blocks[0]
    assert block.chave_nfe == CHAVE_NF
    assert block.numero_nf == "1234"
    assert block.serie == "1"
    assert block.cod_part == "FORN001"
    assert block.ind_oper == "0"


def test_periodo_extraido_do_0000(tmp_path: Path) -> None:
    """SpedIndex deve conter dt_ini e dt_fim extraídos do registro 0000."""
    path = _write_sped(tmp_path, MINIMAL_SPED)
    index = SpedParser().parse(path)

    assert index.dt_ini == "15012025"
    assert index.dt_fim == "31012025"


def test_participant_map(tmp_path: Path) -> None:
    path = _write_sped(tmp_path, MINIMAL_SPED)
    index = SpedParser().parse(path)

    assert "FORN001" in index.participant_map
    assert index.participant_map["FORN001"] == "12345678000199"


def test_e110_line(tmp_path: Path) -> None:
    path = _write_sped(tmp_path, MINIMAL_SPED)
    index = SpedParser().parse(path)

    assert index.e110_line is not None
    # E110 deve estar após E100 e após C990
    assert index.e110_line > 0


def test_antecipacao_pre_existente_marcada_para_remocao(tmp_path: Path) -> None:
    """C195+C197 de antecipação (código conhecido, ex. PA70000010) já
    existentes devem ser marcados em antecipacao_strip_lines — a planilha
    SEFA-PA é a única fonte de verdade e relança tudo do zero, não reconcilia
    com o que já está no arquivo."""
    sped_with_c197 = MINIMAL_SPED.replace(
        "|C990|4|\n",
        "|C195|2||\n|C197|PA70000010|ICMS ANTECIPADO||||500,00|\n|C990|6|\n",
    )
    path = _write_sped(tmp_path, sped_with_c197)
    index = SpedParser().parse(path)

    lines = sped_with_c197.rstrip("\n").split("\n")
    c195_line = next(i for i, raw in enumerate(lines) if raw.startswith("|C195|"))
    c197_line = next(i for i, raw in enumerate(lines) if raw.startswith("|C197|"))

    assert index.antecipacao_strip_lines == {c195_line, c197_line}


def test_e111_e116_antecipacao_pre_existentes_marcados_e_somados(tmp_path: Path) -> None:
    """E111 PA020008 e E116 de COD_REC conhecido (1173) já existentes devem
    ser marcados para remoção, com o valor de cada um acumulado separadamente
    (usado depois para calcular o delta do E110 na substituição)."""
    sped_with_e = MINIMAL_SPED.replace(
        "|E990|4|\n",
        "|E111|PA020008|Outros Creditos|234,50|\n"
        "|E116|005|180,25|10022025|1173|||||012025|\n"
        "|E990|6|\n",
    )
    path = _write_sped(tmp_path, sped_with_e)
    index = SpedParser().parse(path)

    lines = sped_with_e.rstrip("\n").split("\n")
    e111_line = next(i for i, raw in enumerate(lines) if raw.startswith("|E111|"))
    e116_line = next(i for i, raw in enumerate(lines) if raw.startswith("|E116|"))

    assert index.antecipacao_strip_lines == {e111_line, e116_line}
    assert index.antecipacao_stripped_e111_total == Decimal("234.50")
    assert index.antecipacao_stripped_e116_total == Decimal("180.25")


def test_last_child_line_tracks_deepest_child(tmp_path: Path) -> None:
    """last_child_line deve apontar para a última linha filha do bloco C100."""
    path = _write_sped(tmp_path, MINIMAL_SPED)
    index = SpedParser().parse(path)

    block = index.c100_blocks[0]
    # C190 é filho de C100 e é a última linha do bloco neste arquivo
    assert block.last_child_line > block.line_start


def test_multiple_c100_blocks(tmp_path: Path) -> None:
    """Dois blocos C100 devem ser indexados separadamente."""
    two_nfs = """\
|0000|EFD ICMS/IPI|PA|15012025|31012025|12345678000199|EMPRESA TESTE|||||0|
|0001|0|
|0150|FORN001|FORNECEDOR A|1058|11111111000191||||1501|
|0150|FORN002|FORNECEDOR B|1058|22222222000109||||1501|
|0990|4|
|C001|0|
|C100|0|1|FORN001|55|00|1|1234|{chave1}|01012025|05012025|5000,00|0|||5000,00|0|||||||0|0||0|0|
|C190|020|2000,00|5000,00|0,00|500,00|0|0|
|C100|0|1|FORN002|55|00|1|5678|{chave2}|02012025|06012025|3000,00|0|||3000,00|0|||||||0|0||0|0|
|C190|020|1200,00|3000,00|0,00|300,00|0|0|
|C990|6|
|E001|0|
|E100|01012025|31012025|
|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|
|E990|4|
|9001|0|
|9900|9990|1|
|9900|9999|1|
|9990|4|
|9999|20|
""".format(chave1=CHAVE_NF, chave2=CHAVE_NF_2)

    path = _write_sped(tmp_path, two_nfs)
    index = SpedParser().parse(path)

    assert len(index.c100_blocks) == 2
    cnpjs = {index.participant_map.get(b.cod_part) for b in index.c100_blocks}
    assert "11111111000191" in cnpjs
    assert "22222222000109" in cnpjs
