"""Testes unitários para SpedEnricher (Pass 2 — injeção de registros)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest

from app.sped.formatter import parse_decimal
from app.sped.matcher import RawAnticipation, match_anticipations
from app.sped.models import C100Block, MatchedAnticipation
from app.sped.parser import SpedParser
from app.sped.writer import SpedEnricher, _group_e116


CHAVE_NF = "15250112345678000199550010000012340000000010"
CNPJ_FORN = "12345678000199"


def _write_sped(tmp_path: Path, content: str, name: str = "test.txt") -> Path:
    p = tmp_path / name
    p.write_text(dedent(content).lstrip(), encoding="latin-1")
    return p


def _read_records(path: Path) -> list[list[str]]:
    """Lê o arquivo SPED e retorna lista de [campos] por linha."""
    result = []
    with path.open(encoding="latin-1") as f:
        for line in f:
            fields = line.rstrip("\r\n").split("|")
            if len(fields) > 1:
                result.append(fields)
    return result


def _find_records(records: list[list[str]], tipo: str) -> list[list[str]]:
    return [r for r in records if len(r) > 1 and r[1] == tipo]


BASE_SPED = """\
|0000|EFD ICMS/IPI|PA|15012025|31012025|12345678000199|EMPRESA TESTE|||||0|
|0001|0|
|0150|FORN001|FORNECEDOR TESTE LTDA|1058|{cnpj}||||1501|
|0990|3|
|C001|0|
|C100|0|1|FORN001|55|00|1|1234|{chave}|01012025|05012025|5000,00|0|||5000,00|0|||||||0|0||0|0|
|C190|020|2000,00|5000,00|0,00|500,00|0|0|
|C990|4|
|E001|0|
|E100|01012025|31012025|
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
""".format(chave=CHAVE_NF, cnpj=CNPJ_FORN)


def _make_antecipacao(tipo: str, valor: str = "500,00") -> RawAnticipation:
    from app.sped.formatter import parse_decimal
    return RawAnticipation(
        chave_nfe=CHAVE_NF,
        numero_nf="1234",
        serie="1",
        emitente_cnpj=CNPJ_FORN,
        tipo=tipo,
        valor_icms=parse_decimal(valor),
        dare_numero="DAR-2025-001",
        dare_vencimento="10022025",
    )


# ── NORMAL ───────────────────────────────────────────────────────────────────

def test_normal_inserts_c195_and_c197(tmp_path: Path) -> None:
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    ants = [_make_antecipacao("NORMAL")]
    matched, unmatched = match_anticipations(index, ants)

    assert not unmatched
    result = SpedEnricher().enrich(sped, out, index, matched)

    assert result.c197_inserted == 1
    records = _read_records(out)

    c195s = _find_records(records, "C195")
    assert len(c195s) == 1
    assert c195s[0][2] == "PA0010"   # COD_OBS para NORMAL

    c197s = _find_records(records, "C197")
    assert len(c197s) == 1
    assert c197s[0][2] == "PA70000010"
    assert c197s[0][7] == "500,00"  # VL_ICMS — é este campo que o PVA soma para o DEB_ESP

    # C195 deve preceder imediatamente o C197 correspondente
    all_types = [r[1] for r in records]
    c195_pos = all_types.index("C195")
    c197_pos = all_types.index("C197")
    assert c197_pos == c195_pos + 1


def test_normal_updates_e110_vl_deb_esp(tmp_path: Path) -> None:
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    e110s = _find_records(records, "E110")
    assert len(e110s) == 1
    # VL_DEB_ESP é o último campo de valor (penúltimo elemento após split)
    # Formato real: 14 campos de valor → VL_DEB_ESP no índice 15
    assert e110s[0][15] == "500,00"


def test_normal_no_e111(tmp_path: Path) -> None:
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    result = SpedEnricher().enrich(sped, out, index, matched)

    assert result.e111_inserted == 0
    records = _read_records(out)
    assert not _find_records(records, "E111")


def test_normal_inserts_e116(tmp_path: Path) -> None:
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    result = SpedEnricher().enrich(sped, out, index, matched)

    assert result.e116_inserted == 1
    records = _read_records(out)
    e116s = _find_records(records, "E116")
    assert len(e116s) == 1
    assert e116s[0][2] == "005"        # COD_OR: antecipação tributária
    assert e116s[0][3] == "500,00"     # VL_OR
    assert e116s[0][4] == "10022025"   # DT_VCTO: dare_vencimento do _make_antecipacao
    assert e116s[0][5] == "1146"       # COD_REC para NORMAL
    assert e116s[0][7] == ""           # IND_PROC: vazio quando NUM_PROC vazio
    assert e116s[0][10] == "012025"    # MES_REF: MMAAAA derivado de dt_fim "31012025"


# ── ESPECIAL ─────────────────────────────────────────────────────────────────

def test_especial_inserts_c195_c197_no_e111_same_period(tmp_path: Path) -> None:
    """ESPECIAL sempre lança o débito (C195/C197/E116) no período do match —
    mas NÃO o E111 (crédito) neste mesmo arquivo: orientação SEFA-PA 1173 §2
    diz que o crédito só pode ser apropriado no mês SEGUINTE. Sem
    `credit_to_claim` explícito (default 0), nenhum E111 é escrito; o total
    ESPECIAL deste período fica só em `result.especial_total`, pro chamador
    (tasks.py) persistir como crédito pendente."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL")])
    result = SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)

    c195s = _find_records(records, "C195")
    assert len(c195s) == 1
    assert c195s[0][2] == "PA0008"   # COD_OBS para ESPECIAL

    c197s = _find_records(records, "C197")
    assert len(c197s) == 1
    assert c197s[0][2] == "PA70000008"
    assert c197s[0][7] == "500,00"  # VL_ICMS — campo que o PVA soma para o DEB_ESP (não VL_BC_ICMS/campo 5)

    assert not _find_records(records, "E111")
    assert result.e111_inserted == 0
    assert result.especial_total == parse_decimal("500,00")

    e116s = _find_records(records, "E116")
    assert e116s[0][5] == "1173"   # COD_REC para ESPECIAL


def test_credit_to_claim_inserts_e111(tmp_path: Path) -> None:
    """`credit_to_claim` (crédito de um período ANTERIOR desta empresa, já
    apurado e persistido pelo chamador) é o que vira E111 — independente do
    total ESPECIAL deste período. Aqui o período atual não tem ESPECIAL
    nenhum no match (só NORMAL), mas ainda assim lança o E111 do crédito
    pendente que está sendo reivindicado agora."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    result = SpedEnricher().enrich(
        sped, out, index, matched, credit_to_claim=parse_decimal("742,10")
    )

    records = _read_records(out)
    e111s = _find_records(records, "E111")
    assert len(e111s) == 1
    assert e111s[0][2] == "PA020008"
    assert e111s[0][4] == "742,10"
    assert result.e111_inserted == 1
    assert result.especial_total == Decimal("0")   # nada ESPECIAL neste período


# ── CESTA_BASICA ─────────────────────────────────────────────────────────────

def test_cesta_basica_correct_codes(tmp_path: Path) -> None:
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("CESTA_BASICA")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)

    c195s = _find_records(records, "C195")
    assert c195s[0][2] == "PA0011"   # COD_OBS para CESTA_BASICA

    c197s = _find_records(records, "C197")
    assert c197s[0][2] == "PA70000011"

    e116s = _find_records(records, "E116")
    assert e116s[0][5] == "1152"


# ── E116 — consolidação ──────────────────────────────────────────────────────

def _matched_ant(valor: str, tipo: str = "ESPECIAL", dare_vencimento: str | None = None,
                  dare_numero: str | None = None) -> MatchedAnticipation:
    """Constrói um MatchedAnticipation mínimo para testar _group_e116
    isoladamente, sem precisar de um SPED/matcher reais."""
    block = C100Block(
        line_start=0, line_end=1, chave_nfe="", numero_nf="", serie="",
        cod_part="", ind_oper="0", last_child_line=0,
    )
    cod_receita = {"NORMAL": "1146", "ESPECIAL": "1173", "CESTA_BASICA": "1152"}[tipo]
    return MatchedAnticipation(
        c100_block=block, chave_nfe="", numero_nf="", serie="", emitente_cnpj="",
        tipo=tipo, valor_icms=parse_decimal(valor),
        dare_numero=dare_numero, dare_vencimento=dare_vencimento,
        codigo_ajuste_c197="PA70000008", codigo_ajuste_e111="PA020008",
        cod_receita_e116=cod_receita,
    )


def test_e116_consolida_mesmo_tipo_e_vencimento() -> None:
    """Várias antecipações do mesmo tipo/vencimento consolidam num único
    grupo com o valor somado — não um E116 por nota. Reflete a prática real
    (1 DARE por mês por tipo de antecipação, confirmado pelo usuário via
    captura do PVA onde 11 E116 separados apareciam onde deveria haver 1)."""
    matched = [_matched_ant("583,29"), _matched_ant("1382,47"), _matched_ant("542,88")]
    groups = _group_e116(matched, dt_fim="30062026")

    assert len(groups) == 1
    (cod_receita, dt_vcto, _dare), total = next(iter(groups.items()))
    assert total == parse_decimal("2508,64")   # soma 583,29+1382,47+542,88
    assert dt_vcto == "30062026"
    assert cod_receita == "1173"


def test_e116_nao_consolida_tipos_diferentes() -> None:
    """Antecipações de tipos diferentes (COD_REC diferente) NÃO devem
    consolidar — são obrigações distintas."""
    matched = [_matched_ant("583,29", tipo="ESPECIAL"), _matched_ant("100,00", tipo="NORMAL")]
    groups = _group_e116(matched, dt_fim="30062026")

    assert len(groups) == 2
    valores = {v for v in groups.values()}
    assert valores == {parse_decimal("583,29"), parse_decimal("100,00")}


def test_e116_nao_consolida_vencimentos_diferentes() -> None:
    """Antecipações do mesmo tipo mas com DARE de vencimento diferente NÃO
    devem consolidar — são guias de pagamento distintas."""
    matched = [
        _matched_ant("100,00", dare_vencimento="10072026"),
        _matched_ant("200,00", dare_vencimento="20072026"),
    ]
    groups = _group_e116(matched, dt_fim="30062026")

    assert len(groups) == 2


# ── Descarte e relançamento (planilha é a única fonte de verdade) ───────────

def test_c197_antigo_removido_e_relancado_do_zero_pela_planilha(tmp_path: Path) -> None:
    """Regressão do caso real (LUMIERE, NF 601382): a nota tinha 2 itens, só 1
    já tinha C197 lançado (R$693,53 de um total de R$1.159,29 na planilha da
    SEFA-PA) — o item 2 nunca recebeu o dele. Em vez de reconciliar a
    diferença, o motor DESCARTA o C197 antigo (e seu C195 pai) e relança o
    valor CHEIO da planilha — não importa o que já estava no arquivo."""
    sped_with_c197 = BASE_SPED.replace(
        "|C990|4|\n",
        "|C195|2||\n|C197|PA70000008|ICMS ANTECIPADO ESPECIAL||||693,53|\n|C990|6|\n",
    )
    sped = _write_sped(tmp_path, sped_with_c197)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, unmatched = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="1159,29")])

    assert not unmatched
    assert len(matched) == 1
    assert matched[0].valor_icms == parse_decimal("1159,29")   # valor CHEIO da planilha, não a diferença

    result = SpedEnricher().enrich(sped, out, index, matched)
    records = _read_records(out)
    c195s = _find_records(records, "C195")
    c197s = _find_records(records, "C197")
    assert len(c195s) == 1                     # o antigo foi removido, só sobra o novo par
    assert len(c197s) == 1
    assert c197s[0][7] == "1159,29"             # valor cheio da planilha
    assert result.c197_inserted == 1


def test_e111_e116_antigos_removidos_e_relancados_do_zero(tmp_path: Path) -> None:
    """Regressão do caso real (LUMIERE): havia E111 PA020008 (R$2.340,37) e
    E116 (R$1.855,99, COD_REC 1173) pré-existentes no SPED, refletidos no E110
    (campo 8 e DEB_ESP). Em vez de acumular a planilha em cima deles, o motor
    descarta os dois e relança do zero — só o total atual (credit_to_claim
    pro E111/campo 8, matched pro E116) deve sobrar no arquivo final, não a
    soma com o que já estava lá (isso é o que causava a divergência 'soma
    E116 ≠ planilha' que o usuário reportou). credit_to_claim=500,00 aqui só
    pra exercitar o mesmo mecanismo de substituição do campo 8 — não precisa
    ter relação com o total ESPECIAL do match (E116/DEB_ESP), que agora é
    reportado separadamente."""
    e110_baseline = "|E110|0,00|0,00|0,00|0,00|0,00|0,00|2340,37|0,00|0,00|0,00|0,00|0,00|0,00|1855,99|\n"
    sped_with_e = (
        BASE_SPED
        .replace("|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|\n", e110_baseline)
        .replace(
            "|E990|4|\n",
            "|E111|PA020008|Outros Creditos|2340,37|\n"
            "|E116|005|1855,99|14072026|1173|||||012025|\n"
            "|E990|6|\n",
        )
    )
    sped = _write_sped(tmp_path, sped_with_e)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="500,00")])
    SpedEnricher().enrich(sped, out, index, matched, credit_to_claim=parse_decimal("500,00"))

    records = _read_records(out)
    e111s = _find_records(records, "E111")
    assert len(e111s) == 1
    assert e111s[0][4] == "500,00"   # só o novo total da planilha, não acumulado com 2340,37

    e116s = _find_records(records, "E116")
    assert len(e116s) == 1
    assert e116s[0][3] == "500,00"   # só o novo total da planilha, não acumulado com 1855,99

    e110s = _find_records(records, "E110")
    assert e110s[0][8] == "500,00"    # VL_TOT_AJ_CREDITOS substituído, não acumulado
    assert e110s[0][15] == "500,00"   # DEB_ESP substituído, não acumulado


# ── Fallback de match por CNPJ+número+série ──────────────────────────────────

def test_fallback_match_without_chave(tmp_path: Path) -> None:
    """Deve fazer match mesmo sem chave NF-e (NF antiga)."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)

    from app.sped.formatter import parse_decimal
    ant_sem_chave = RawAnticipation(
        chave_nfe="",   # sem chave
        numero_nf="1234",
        serie="1",
        emitente_cnpj=CNPJ_FORN,
        tipo="NORMAL",
        valor_icms=parse_decimal("500,00"),
        dare_numero=None,
        dare_vencimento=None,
    )
    matched, unmatched = match_anticipations(index, [ant_sem_chave])

    assert len(matched) == 1
    assert len(unmatched) == 0


# ── Contagens de fechamento ───────────────────────────────────────────────────

def test_c990_count_updated(tmp_path: Path) -> None:
    """C990 deve refletir os C195+C197 inseridos."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    c990s = _find_records(records, "C990")
    assert len(c990s) == 1
    # Original era 4, adicionamos 1 C195 + 1 C197 → deve ser 6
    assert int(c990s[0][2]) == 6


def test_e990_count_updated(tmp_path: Path) -> None:
    """E990 deve refletir os E116 inseridos."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    e990s = _find_records(records, "E990")
    assert len(e990s) == 1
    # Original era 4 (E001, E100, E110, E990), adicionamos 1 E116 → deve ser 5
    assert int(e990s[0][2]) == 5


def test_9999_total_updated(tmp_path: Path) -> None:
    """9999 deve refletir todas as linhas inseridas."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"

    original_total = sum(1 for _ in sped.open(encoding="latin-1"))

    index = SpedParser().parse(sped)
    # NORMAL: +1 0460 + 1 C195 + 1 C197 + 1 E116 = +4 linhas de conteúdo
    # + 4 novas entradas 9900 (0460, C195, C197, E116) = +8 linhas novas no arquivo
    # 9999 armazena valor inicial (22) + total_additions (4) + new_9900_count (4) = 30
    # original_total (linhas físicas no arquivo) = 24; 30 = 24 + 6
    matched, _ = match_anticipations(index, [_make_antecipacao("NORMAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    nines = _find_records(records, "9999")
    assert len(nines) == 1
    assert int(nines[0][2]) == original_total + 6


# ── E110 — atualização por tipo ──────────────────────────────────────────────

def test_especial_updates_e110_vl_tot_aj_creditos_and_deb_esp(tmp_path: Path) -> None:
    """VL_TOT_AJ_CREDITOS (crédito via E111) reflete credit_to_claim (crédito
    de período anterior sendo reivindicado agora); DEB_ESP (contraponto do
    E116 na apuração) reflete o total ESPECIAL do match deste período — são
    independentes desde a mudança de timing do crédito (SEFA-PA 1173 §2).
    Aqui os dois coincidem (500,00) só por simplicidade do teste."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL")])
    SpedEnricher().enrich(sped, out, index, matched, credit_to_claim=parse_decimal("500,00"))

    records = _read_records(out)
    e110s = _find_records(records, "E110")
    assert len(e110s) == 1
    assert e110s[0][8] == "500,00"    # VL_TOT_AJ_CREDITOS incrementado
    assert e110s[0][15] == "500,00"   # DEB_ESP também incrementado (contraponto do E116)
    assert e110s[0][14] == "500,00"   # VL_SLD_CREDOR_TRANSPORTAR reapurado (0 + 500 credito - 0 debito)


def test_e110_reapuracao_cenario_credor_caso_real(tmp_path: Path) -> None:
    """Regressão do caso real (validação PVA de 08/07/2026): motor incrementava
    VL_TOT_AJ_CREDITOS sem repropagar para VL_SLD_CREDOR_TRANSPORTAR, e o PVA
    acusava 'Saldo credor de ICMS apurado incorretamente' com valor esperado
    131679,68 contra os 130291,75 gravados pelo motor (diferença de 1387,93 —
    exatamente o total processado). Os campos abaixo são os mesmos do E110 real
    (VL_TOT_AJ_CREDITOS já com o saldo PA020008 anterior de 3686,79)."""
    e110_baseline = (
        "|E110|158308,57|0,00|0,00|6702,18|208543,07|0,00|3686,79|0,00|"
        "83072,64|0,00|0,00|0,00|0,00|0,00|\n"
    )
    sped = _write_sped(
        tmp_path, BASE_SPED.replace("|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|\n", e110_baseline)
    )
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="1387,93")])
    result = SpedEnricher().enrich(
        sped, out, index, matched, credit_to_claim=parse_decimal("1387,93")
    )
    # débito deste período, vira crédito pendente (não é o que virou E111 aqui)
    assert result.especial_total == parse_decimal("1387,93")

    records = _read_records(out)
    e110s = _find_records(records, "E110")
    assert e110s[0][8] == "5074,72"     # VL_TOT_AJ_CREDITOS: 3686,79 + 1387,93 (bate com o E111 real)
    assert e110s[0][15] == "1387,93"    # DEB_ESP: contraponto do novo E116
    assert e110s[0][11] == "0,00"       # VL_SLD_APURADO: segue credor
    assert e110s[0][13] == "0,00"       # VL_ICMS_RECOLHER: nada a recolher na apuração normal
    assert e110s[0][14] == "131679,68"  # VL_SLD_CREDOR_TRANSPORTAR: exatamente o "Valor Esperado" do PVA


def test_e110_reapuracao_cenario_devedor(tmp_path: Path) -> None:
    """Quando débitos > créditos mesmo após o crédito da antecipação, o saldo
    deve ir para VL_SLD_APURADO/VL_ICMS_RECOLHER (com deduções), não para
    VL_SLD_CREDOR_TRANSPORTAR — branch não exercitado pelos dados reais."""
    e110_baseline = "|E110|1000,00|0,00|0,00|0,00|0,00|0,00|0,00|0,00|0,00|0,00|50,00|0,00|0,00|0,00|\n"
    sped = _write_sped(
        tmp_path, BASE_SPED.replace("|E110|0|0|0|0|0|0|0|0|0|0|0|0|0|0|\n", e110_baseline)
    )
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="200,00")])
    SpedEnricher().enrich(sped, out, index, matched, credit_to_claim=parse_decimal("200,00"))

    records = _read_records(out)
    e110s = _find_records(records, "E110")
    assert e110s[0][8] == "200,00"    # VL_TOT_AJ_CREDITOS: 0 + 200
    assert e110s[0][15] == "200,00"   # DEB_ESP: 0 + 200
    assert e110s[0][11] == "800,00"   # VL_SLD_APURADO: 1000 débito - 200 crédito
    assert e110s[0][13] == "750,00"   # VL_ICMS_RECOLHER: 800 - 50 de dedução (VL_TOT_DED)
    assert e110s[0][14] == "0,00"     # VL_SLD_CREDOR_TRANSPORTAR: não há saldo credor


def test_c197_vl_icms_no_campo_correto_caso_real_lumiere(tmp_path: Path) -> None:
    """Regressão do caso real (LUMIERE, validação PVA de 13/07/2026): o PVA
    calcula o DEB_ESP esperado (campo 15 do E110) somando o campo VL_ICMS
    (posição 7) dos C197 PA70000008 — não o VL_BC_ICMS (posição 5). Um C197
    pré-existente e correto no SPED real tinha VL_BC_ICMS=4623,52/VL_ICMS=693,53
    e VL_BC_ICMS=7749,76/VL_ICMS=1162,46 (693,53+1162,46=1855,99, batendo
    exato com o DEB_ESP pré-existente). O motor gravava o valor no campo
    errado (VL_BC_ICMS) e deixava VL_ICMS vazio, fazendo o PVA computar as
    novas antecipações como se não tivessem nenhum valor."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="693,53")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    c197s = _find_records(records, "C197")
    assert c197s[0][4] == ""         # COD_ITEM: não disponível na SEFA-PA
    assert c197s[0][5] == ""         # VL_BC_ICMS: não disponível na SEFA-PA (NÃO deve levar o valor)
    assert c197s[0][6] == ""         # ALIQ_ICMS: não disponível na SEFA-PA
    assert c197s[0][7] == "693,53"   # VL_ICMS: aqui vai o valor da antecipação
    assert c197s[0][8] == ""         # VL_OUTROS


# ── 0460 — registro de observação ────────────────────────────────────────────

def test_inserts_0460_when_missing(tmp_path: Path) -> None:
    """0460 deve ser inserido antes do 0990 quando COD_OBS não está cadastrado."""
    sped = _write_sped(tmp_path, BASE_SPED)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    recs_0460 = _find_records(records, "0460")
    assert len(recs_0460) == 1
    assert recs_0460[0][2] == "PA0008"

    # 0460 deve aparecer antes do 0990
    all_types = [r[1] for r in records]
    assert all_types.index("0460") < all_types.index("0990")


def test_no_duplicate_0460_when_already_present(tmp_path: Path) -> None:
    """0460 NÃO deve ser duplicado se já existe no SPED original."""
    sped_with_0460 = BASE_SPED.replace(
        "|0990|3|\n",
        "|0460|PA0008|ICMS ANTECIPADO ESPECIAL|\n|0990|4|\n",
    )
    sped = _write_sped(tmp_path, sped_with_0460)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    recs_0460 = _find_records(records, "0460")
    assert len(recs_0460) == 1           # apenas o original, sem duplicata
    assert recs_0460[0][2] == "PA0008"


def test_0460_orfao_apos_remocao_de_antecipacao_antiga_e_removido(tmp_path: Path) -> None:
    """Regressão do caso real (PVA): o SPED original tinha um C195(COD_OBS=2)
    pai do C197 PA70000008 antigo, e um 0460(COD_OBS=2) na tabela de
    observações do bloco 0. Como a planilha SEFA-PA é a única fonte de
    verdade, o motor descarta o C195/C197 antigo e relança do zero com um novo
    COD_OBS (PA0008, de codigos_ajuste.py) — mas o 0460 antigo não era
    removido, ficando órfão (declarado, mas não referenciado por nenhum C195
    remanescente). O PVA acusa isso como "Não informar código da observação,
    se não referenciado em pelo menos um dos demais blocos"."""
    sped_with_old = (
        BASE_SPED
        .replace(
            "|0990|3|\n",
            "|0460|2|ANTECIPACAO ESPECIAL - DECRETO N.º 744/2007|\n|0990|4|\n",
        )
        .replace(
            "|C990|4|\n",
            "|C195|2||\n|C197|PA70000008|ICMS ANTECIPADO ESPECIAL||||693,53|\n|C990|6|\n",
        )
    )
    sped = _write_sped(tmp_path, sped_with_old)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="1159,29")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    recs_0460 = _find_records(records, "0460")
    codes = [r[2] for r in recs_0460]
    assert "2" not in codes             # 0460 órfão foi removido
    assert codes == ["PA0008"]           # só sobra o novo, referenciado pelo C195 fresco


def test_0460_nao_removido_se_ainda_referenciado_por_outro_c195(tmp_path: Path) -> None:
    """Guarda contra remoção excessiva: se o mesmo COD_OBS também é usado por
    um C195 que NÃO é de antecipação (não bate com nenhum código conhecido em
    codigos_ajuste.CODIGOS, então nunca é marcado para remoção), o 0460
    correspondente deve permanecer no arquivo."""
    sped_with_shared_obs = (
        BASE_SPED
        .replace(
            "|0990|3|\n",
            "|0460|2|ANTECIPACAO ESPECIAL - DECRETO N.º 744/2007|\n|0990|4|\n",
        )
        .replace(
            "|C990|4|\n",
            "|C195|2||\n|C197|PA70000008|ICMS ANTECIPADO ESPECIAL||||693,53|\n"
            "|C195|2||\n|C197|PA99999999|OUTRO AJUSTE NAO RELACIONADO||||10,00|\n"
            "|C990|8|\n",
        )
    )
    sped = _write_sped(tmp_path, sped_with_shared_obs)
    out = tmp_path / "out.txt"
    index = SpedParser().parse(sped)
    matched, _ = match_anticipations(index, [_make_antecipacao("ESPECIAL", valor="1159,29")])
    SpedEnricher().enrich(sped, out, index, matched)

    records = _read_records(out)
    recs_0460 = _find_records(records, "0460")
    codes = {r[2] for r in recs_0460}
    assert codes == {"2", "PA0008"}      # "2" sobrevive: referenciado pelo C195 não-antecipação

    c197s = _find_records(records, "C197")
    codigos_c197 = {r[2] for r in c197s}
    assert codigos_c197 == {"PA70000008", "PA99999999"}  # ajuste não relacionado não foi tocado
