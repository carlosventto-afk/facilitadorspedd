"""
SPED EFD ICMS/IPI — SpedEnricher (Pass 2).

A planilha SEFA-PA é a única fonte de verdade para antecipação: qualquer
C195/C197/E111/E116 de antecipação já existente no SPED original (detectado
no parser.py via os códigos em codigos_ajuste.CODIGOS) é removido, e tudo é
relançado do zero a partir da planilha — não há reconciliação/acúmulo com o
que já estava no arquivo.

Injeta registros C197 após blocos C100 correspondentes, atualiza E110
(VL_TOT_AJ_CREDITOS para ESPECIAL; DEB_ESP para todos os tipos, pois todos
geram E116) e reapura o saldo (VL_SLD_APURADO / VL_ICMS_RECOLHER /
VL_SLD_CREDOR_TRANSPORTAR), insere E111 para ESPECIAL, insere E116 e adiciona
registros 0460 ao bloco 0.

Atualiza registros de fechamento (0990, C990, E990, 9999) e contagens
por tipo de registro no bloco 9 (9900).
"""
from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.sped.codigos_ajuste import CODIGOS
from app.sped.formatter import (
    build_pipe_record,
    format_decimal,
    parse_decimal,
)
from app.sped.models import MatchedAnticipation, ProcessingResult, SpedIndex

logger = logging.getLogger(__name__)

# E116 — Obrigação de Pagamento do ICMS
# |E116|COD_OR|VL_OR|DT_VCTO|COD_REC|NUM_PROC|IND_PROC|PROC|TXT_COMPL|MES_REF|
# COD_OR "005" = Antecipação tributária. Confirmado contra um E116 pré-existente
# e correto no SPED real (mesmo COD_REC 1173, COD_OR gravado como "005"), não
# "000" (ICMS a recolher — reservado para a obrigação da apuração normal).
_E116_COD_OR = "005"   # Antecipação tributária

# Índices dos campos de valor do E110 após split por '|' (índice 0 é vazio, 1 é "E110"):
# |E110|VL_TOT_DEBITOS|VL_AJ_DEBITOS|VL_TOT_AJ_DEBITOS|VL_ESTORNOS_CRED|VL_TOT_CREDITOS|
#       [2]            [3]          [4]                [5]              [6]
#  VL_AJ_CREDITOS|VL_TOT_AJ_CREDITOS|VL_ESTORNOS_DEB|VL_SLD_CREDOR_ANT|VL_SLD_APURADO|
#  [7]            [8]                [9]             [10]              [11]
#  VL_TOT_DED|VL_ICMS_RECOLHER|VL_SLD_CREDOR_TRANSPORTAR|DEB_ESP|
#  [12]        [13]             [14]                       [15]
#
# VL_TOT_AJ_CREDITOS (8) = créditos via E111 (tipo ESPECIAL, código PA020008).
# DEB_ESP (15, último campo de valor) = contraponto de TODAS as antecipações
# (NORMAL + ESPECIAL + CESTA_BASICA) que geram E116, pois o PVA valida que
# soma(E116.VL_OR) == VL_ICMS_RECOLHER + DEB_ESP.
#
# VL_SLD_APURADO (11), VL_ICMS_RECOLHER (13) e VL_SLD_CREDOR_TRANSPORTAR (14)
# são campos derivados: precisam ser reapurados sempre que 8 ou 15 mudam,
# senão o PVA acusa "Saldo credor de ICMS apurado incorretamente".
_E110_VL_TOT_DEBITOS_IDX = 2
_E110_VL_TOT_AJ_DEBITOS_IDX = 4
_E110_VL_ESTORNOS_CRED_IDX = 5
_E110_VL_TOT_CREDITOS_IDX = 6
_E110_VL_TOT_AJ_CREDITOS_IDX = 8
_E110_VL_ESTORNOS_DEB_IDX = 9
_E110_VL_SLD_CREDOR_ANT_IDX = 10
_E110_VL_SLD_APURADO_IDX = 11
_E110_VL_TOT_DED_IDX = 12
_E110_VL_ICMS_RECOLHER_IDX = 13
_E110_VL_SLD_CREDOR_TRANSPORTAR_IDX = 14


def _split(raw: str) -> list[str]:
    return raw.rstrip("\r\n").split("|")


def _build_c195(m: MatchedAnticipation) -> str:
    """Constrói o registro C195 (pai obrigatório do C197 na hierarquia SPED).

    Hierarquia: C100 → C195 → C197
    COD_OBS: código da Tabela 5.3 (observações de lançamentos fiscais) — específico do PA.
    """
    return build_pipe_record(
        "C195",
        CODIGOS[m.tipo].obs_c195,
        CODIGOS[m.tipo].descricao_c197,  # TXT_COMPL (opcional, para rastreabilidade)
    )


def _build_c197(m: MatchedAnticipation) -> str:
    """Constrói um registro C197 para uma antecipação (filho de C195).

    Leiaute Guia Prático EFD ICMS/IPI — 8 campos:
    |REG|COD_AJ|DESCR_COMPL_AJ|COD_ITEM|VL_BC_ICMS|ALIQ_ICMS|VL_ICMS|VL_OUTROS|

    Confirmado contra um C197 PA70000008 pré-existente e correto num SPED real
    (VL_BC_ICMS = valor do item do C170; VL_ICMS = 15% de VL_BC_ICMS — a soma
    dos VL_ICMS de todos os C197 PA70000008 é exatamente o que o Validador SPED
    soma para o campo 15/DEB_ESP do E110). O código anterior gravava
    m.valor_icms no campo VL_BC_ICMS (então chamado, erradamente, de "VL_AJ") e
    deixava VL_ICMS vazio — por isso o PVA computava DEB_ESP esperado como se
    nossos C197 não tivessem nenhum valor.
    """
    return build_pipe_record(
        "C197",
        m.codigo_ajuste_c197,
        CODIGOS[m.tipo].descricao_c197,
        "",                           # COD_ITEM (item do C170 — não disponível na SEFA-PA, que agrega por nota)
        "",                           # VL_BC_ICMS (base de cálculo — não disponível na SEFA-PA)
        "",                           # ALIQ_ICMS (alíquota — não disponível na SEFA-PA)
        format_decimal(m.valor_icms), # VL_ICMS — valor do ICMS do ajuste; é isto que o PVA soma para o DEB_ESP
        "",                           # VL_OUTROS
    )


# |E116|COD_OR|VL_OR|DT_VCTO|COD_REC|NUM_PROC|IND_PROC|PROC|TXT_COMPL|MES_REF|


def _group_e116(
    matched: list[MatchedAnticipation], dt_fim: str
) -> dict[tuple[str, str, str], Decimal]:
    """Agrupa antecipações por (COD_REC, DT_VCTO, DARE) e soma o valor de cada
    grupo — a obrigação de pagamento é por guia de recolhimento (DARE/DAR),
    não por nota fiscal, então todas as antecipações do mesmo tipo com o
    mesmo vencimento caem no mesmo DARE e devem virar um único E116.
    """
    groups: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for m in matched:
        # DT_VCTO: data do DARE/DAR; fallback para fim do período quando não disponível
        dt_vcto = m.dare_vencimento or dt_fim
        key = (m.cod_receita_e116, dt_vcto, m.dare_numero or "")
        groups[key] += m.valor_icms
    return dict(groups)


def _build_e116_record(cod_receita: str, dt_vcto: str, dare_numero: str, valor: Decimal, dt_fim: str) -> str:
    """Constrói um registro E116 novo para um grupo (COD_REC, DT_VCTO, DARE)."""
    # MES_REF: competência no formato MMAAAA — extraído dos últimos 6 chars de DDMMAAAA
    mes_ref = dt_fim[2:] if len(dt_fim) >= 8 else ""
    return build_pipe_record(
        "E116",
        _E116_COD_OR,
        format_decimal(valor),
        dt_vcto,                # DT_VCTO em DDMMAAAA (obrigatório)
        cod_receita,             # COD_REC: 1146 / 1173 / 1152
        "",                      # NUM_PROC
        "",                      # IND_PROC: vazio quando NUM_PROC não preenchido
        "",                      # PROC
        dare_numero,             # TXT_COMPL: referência do DARE/DAR
        mes_ref,                 # MES_REF em MMAAAA (obrigatório)
    )


def _rewrite_e110(raw: str, deb_esp_delta: Decimal, aj_creditos_delta: Decimal = Decimal("0")) -> str:
    """Atualiza o registro E110 com os deltas de cada tipo de antecipação e
    reapura o saldo (campos derivados 11/13/14).

    - aj_creditos_delta → soma em VL_TOT_AJ_CREDITOS (fields[8]): (novo total
      ESPECIAL da planilha) − (total antigo de E111 de antecipação removido).
      Pode ser negativo (planilha atual menor que o que havia antes).
    - deb_esp_delta     → soma em DEB_ESP (último campo de valor): (novo total
      de todas as antecipações da planilha) − (total antigo de E116 de
      antecipação removido). Também pode ser negativo.

    Os dois deltas representam SUBSTITUIÇÃO (planilha é a única fonte de
    verdade), não acúmulo — por isso podem ser negativos, e por isso são
    aplicados mesmo quando != 0 (não só quando > 0).

    Depois de aplicar os deltas, os campos 11 (VL_SLD_APURADO), 13
    (VL_ICMS_RECOLHER) e 14 (VL_SLD_CREDOR_TRANSPORTAR) são recalculados do
    zero a partir dos demais campos — eles são derivados e ficam
    inconsistentes se apenas o campo 8 for incrementado isoladamente
    (é exatamente o que o PVA acusa como "Saldo credor de ICMS apurado
    incorretamente").

    Fórmula (validada campo a campo contra o Validador SPED):
        créditos = VL_TOT_CREDITOS + VL_TOT_AJ_CREDITOS + VL_ESTORNOS_DEB + VL_SLD_CREDOR_ANT
        débitos  = VL_TOT_DEBITOS + VL_TOT_AJ_DEBITOS + VL_ESTORNOS_CRED
        se créditos >= débitos: saldo credor a transportar = créditos - débitos
        senão: ICMS a recolher = (débitos - créditos) - VL_TOT_DED
    """
    fields = _split(raw)
    if not fields or fields[-1] != "":
        fields.append("")
    # Garante campos até DEB_ESP + terminador vazio; insere sempre antes do
    # terminador (fields[-1] == "" neste ponto, garantido pelo if acima).
    while len(fields) <= _E110_VL_SLD_CREDOR_TRANSPORTAR_IDX + 2:
        fields.insert(-1, "0,00")

    vl_deb_esp_idx = len(fields) - 2  # último campo de valor

    if aj_creditos_delta != Decimal("0"):
        current = parse_decimal(fields[_E110_VL_TOT_AJ_CREDITOS_IDX])
        fields[_E110_VL_TOT_AJ_CREDITOS_IDX] = format_decimal(current + aj_creditos_delta)

    if deb_esp_delta != Decimal("0"):
        current = parse_decimal(fields[vl_deb_esp_idx])
        fields[vl_deb_esp_idx] = format_decimal(current + deb_esp_delta)

    creditos = (
        parse_decimal(fields[_E110_VL_TOT_CREDITOS_IDX])
        + parse_decimal(fields[_E110_VL_TOT_AJ_CREDITOS_IDX])
        + parse_decimal(fields[_E110_VL_ESTORNOS_DEB_IDX])
        + parse_decimal(fields[_E110_VL_SLD_CREDOR_ANT_IDX])
    )
    debitos = (
        parse_decimal(fields[_E110_VL_TOT_DEBITOS_IDX])
        + parse_decimal(fields[_E110_VL_TOT_AJ_DEBITOS_IDX])
        + parse_decimal(fields[_E110_VL_ESTORNOS_CRED_IDX])
    )

    if creditos >= debitos:
        fields[_E110_VL_SLD_APURADO_IDX] = format_decimal(Decimal("0"))
        fields[_E110_VL_ICMS_RECOLHER_IDX] = format_decimal(Decimal("0"))
        fields[_E110_VL_SLD_CREDOR_TRANSPORTAR_IDX] = format_decimal(creditos - debitos)
    else:
        saldo_devedor = debitos - creditos
        deducoes = parse_decimal(fields[_E110_VL_TOT_DED_IDX])
        fields[_E110_VL_SLD_APURADO_IDX] = format_decimal(saldo_devedor)
        fields[_E110_VL_ICMS_RECOLHER_IDX] = format_decimal(saldo_devedor - deducoes)
        fields[_E110_VL_SLD_CREDOR_TRANSPORTAR_IDX] = format_decimal(Decimal("0"))

    return "|".join(fields) + "\n"


class SpedEnricher:
    """
    Segundo passo do processamento SPED.

    Recebe o arquivo original, o SpedIndex (do parser.py) e as antecipações
    já associadas a blocos C100 (do matcher.py), e produz o arquivo enriquecido.
    """

    def enrich(
        self,
        input_path: Path,
        output_path: Path,
        index: SpedIndex,
        matched: list[MatchedAnticipation],
    ) -> ProcessingResult:
        result = ProcessingResult(
            anticipations_total=len(matched),
            anticipations_matched=len(matched),
            nfs_found=len(index.c100_blocks),
            total_icms_value=sum(m.valor_icms for m in matched),
        )

        if not matched:
            shutil.copy2(str(input_path), str(output_path))
            return result

        # ── Pré-computar injeções ────────────────────────────────────────────

        # Agrupa (C195, C197) por linha de último filho do bloco C100
        # Hierarquia obrigatória: C100 → C195 → C197
        c197_by_line: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for m in matched:
            c197_by_line[m.c100_block.last_child_line].append(
                (_build_c195(m), _build_c197(m))
            )

        # ESPECIAL → também credita E111 PA020008 → E110.VL_TOT_AJ_CREDITOS (outros créditos).
        # A planilha SEFA-PA é a única fonte de verdade: qualquer C197/E111/E116
        # de antecipação pré-existente (index.antecipacao_strip_lines, calculado
        # no parser.py) é descartado no streaming abaixo e substituído do zero
        # pelo que está sendo calculado aqui — não se acumula com o que havia.
        especial_total: Decimal = sum(
            m.valor_icms for m in matched if m.codigo_ajuste_e111
        )

        # Todos os tipos (NORMAL + ESPECIAL + CESTA_BASICA) → E110.DEB_ESP:
        # todos geram E116 (obrigação de recolhimento), e o PVA exige que
        # soma(E116.VL_OR) == VL_ICMS_RECOLHER + DEB_ESP do E110.
        total_for_deb_esp: Decimal = sum(m.valor_icms for m in matched)

        # E116 consolidado por (COD_REC, DT_VCTO, DARE) — não um por antecipação.
        # Sempre novo: qualquer E116 de antecipação pré-existente é removido
        # (index.antecipacao_strip_lines), então não há registro para fundir.
        e116_records: list[str] = [
            _build_e116_record(cod_receita, dt_vcto, dare_numero, total, index.dt_fim)
            for (cod_receita, dt_vcto, dare_numero), total in _group_e116(matched, index.dt_fim).items()
        ]

        # Registros 0460 a inserir: COD_OBS usados em C195 ainda não cadastrados no bloco 0
        codes_used_by_new_c195: set[str] = {CODIGOS[m.tipo].obs_c195 for m in matched}
        obs_to_add: dict[str, str] = {}
        for m in matched:
            code = CODIGOS[m.tipo].obs_c195
            if code not in index.existing_0460_codes and code not in obs_to_add:
                obs_to_add[code] = CODIGOS[m.tipo].descricao_c197

        # Registros 0460 órfãos a remover: já cadastrados no bloco 0, mas cujo
        # único C195 referenciador foi removido junto do C197 de antecipação
        # antigo (planilha SEFA-PA relançada do zero) — sem isso, o PVA acusa
        # "COD_OBS não referenciado em pelo menos um dos demais blocos".
        orphaned_0460_codes: set[str] = {
            code
            for code in index.existing_0460_codes
            if code not in index.existing_0460_still_referenced
            and code not in codes_used_by_new_c195
        }

        # Deltas do E110: (novo total da planilha) − (total antigo de antecipação
        # que está sendo removido) — substituição, não acúmulo. Podem ser
        # negativos (ex.: planilha atual não cobre tudo que havia antes).
        aj_creditos_delta = especial_total - index.antecipacao_stripped_e111_total
        deb_esp_delta = total_for_deb_esp - index.antecipacao_stripped_e116_total

        # ── Streaming Pass 2 ─────────────────────────────────────────────────

        bloco0_additions = 0  # novos registros 0460 inseridos (para 0990)
        c_additions = 0       # variação líquida de linhas no bloco C (para C990)
        e_additions = 0       # variação líquida de linhas no bloco E (para E990)
        total_additions = 0   # variação líquida total (para 9999)
        net_counts: dict[str, int] = defaultdict(int)   # variação por tipo (para 9900)

        nine_block_buffer: list[str] = []
        buffering_nine = False

        with (
            input_path.open(encoding="latin-1") as fin,
            output_path.open("w", encoding="latin-1") as fout,
        ):
            for line_number, raw in enumerate(fin):
                fields = _split(raw)
                reg = fields[1] if len(fields) > 1 else ""

                # ── Bloco 9: bufferiza para pós-processamento ────────────────
                if buffering_nine or reg == "9001":
                    buffering_nine = True
                    nine_block_buffer.append(raw)
                    continue

                # ── Bloco 0: 0460 órfão de antecipação removida — remove ────
                if reg == "0460" and len(fields) > 2 and fields[2].strip() in orphaned_0460_codes:
                    bloco0_additions -= 1
                    total_additions -= 1
                    net_counts["0460"] -= 1
                    logger.info("Removendo 0460 órfão (COD_OBS=%s)", fields[2].strip())
                    continue

                # ── Bloco 0: closure — insere 0460 faltantes antes de fechar ─
                elif reg == "0990":
                    if obs_to_add:
                        for code, txt in sorted(obs_to_add.items()):
                            rec_0460 = build_pipe_record("0460", code, txt)
                            fout.write(rec_0460)
                            bloco0_additions += 1
                            total_additions += 1
                            net_counts["0460"] += 1
                            logger.info("0460 inserido: %s", code)
                    orig = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 0
                    fout.write(build_pipe_record("0990", str(orig + bloco0_additions)))
                    continue

                # ── Bloco C: closure ─────────────────────────────────────────
                elif reg == "C990":
                    orig = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 0
                    fout.write(build_pipe_record("C990", str(orig + c_additions)))
                    continue

                # ── Bloco E: E110 ────────────────────────────────────────────
                elif reg == "E110" and line_number == index.e110_line:
                    fout.write(_rewrite_e110(raw, deb_esp_delta, aj_creditos_delta))
                    # Injeta E111 PA020008 fresco (soma só da planilha atual —
                    # qualquer E111 de antecipação antigo foi removido abaixo)
                    if especial_total > Decimal("0"):
                        e111_rec = build_pipe_record(
                            "E111",
                            CODIGOS["ESPECIAL"].e111 or "",
                            CODIGOS["ESPECIAL"].descricao_e111 or "",
                            format_decimal(especial_total),
                        )
                        fout.write(e111_rec)
                        e_additions += 1
                        total_additions += 1
                        net_counts["E111"] += 1
                        result.e111_inserted += 1
                        logger.info("E111 PA020008 inserido: %s", format_decimal(especial_total))
                    continue

                # ── Bloco E: E111/E116 de antecipação pré-existente — remove ─
                elif reg in ("E111", "E116") and line_number in index.antecipacao_strip_lines:
                    e_additions -= 1
                    total_additions -= 1
                    net_counts[reg] -= 1
                    logger.info("Removendo %s de antecipação pré-existente na linha %d", reg, line_number)
                    continue

                # ── Bloco E: E990 — injeta E116 antes de fechar ──────────────
                elif reg == "E990":
                    if e116_records:
                        for e116_rec in e116_records:
                            fout.write(e116_rec)
                        n = len(e116_records)
                        e_additions += n
                        total_additions += n
                        net_counts["E116"] += n
                        result.e116_inserted += n
                        logger.info("%d registro(s) E116 inserido(s)", n)

                    orig = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 0
                    fout.write(build_pipe_record("E990", str(orig + e_additions)))
                    continue

                # ── Bloco C: C195/C197 de antecipação pré-existente — remove ─
                elif reg in ("C195", "C197") and line_number in index.antecipacao_strip_lines:
                    c_additions -= 1
                    total_additions -= 1
                    net_counts[reg] -= 1
                    logger.info("Removendo %s de antecipação pré-existente na linha %d", reg, line_number)
                    # Não faz "continue": ainda pode ser o last_child_line onde
                    # o C195+C197 novo (fresco, da planilha) deve ser inserido.

                else:
                    # ── Escrita normal ───────────────────────────────────────
                    fout.write(raw)

                # Injeta C195+C197 após o último filho do bloco C100 correspondente
                # Hierarquia obrigatória SPED: C100 → C195 → C197. Roda mesmo
                # quando a linha atual foi removida acima (linha antiga de
                # antecipação sendo substituída pela nova, no mesmo lugar).
                if line_number in c197_by_line:
                    pairs = c197_by_line[line_number]
                    for c195_rec, c197_rec in pairs:
                        fout.write(c195_rec)
                        fout.write(c197_rec)
                    n = len(pairs)
                    c_additions += n * 2   # C195 + C197 para cada antecipação
                    total_additions += n * 2
                    net_counts["C195"] += n
                    net_counts["C197"] += n
                    result.c197_inserted += n

        # ── Processar e anexar bloco 9 ───────────────────────────────────────
        nine_output = self._process_nine_block(nine_block_buffer, total_additions, net_counts)
        with output_path.open("a", encoding="latin-1") as fout:
            for line in nine_output:
                fout.write(line)

        logger.info(
            "Enriquecimento concluído: %d C197 | %d E111 | %d E116",
            result.c197_inserted, result.e111_inserted, result.e116_inserted,
        )
        return result

    def _process_nine_block(
        self,
        raw_lines: list[str],
        total_additions: int,
        net_counts: dict[str, int],
    ) -> list[str]:
        """
        Processa o bloco 9 atualizando 9900 (contagem por tipo), 9990 e 9999.

        Regra: se um tipo de registro (C197, E111, E116) já tem uma linha 9900,
        ela é incrementada pelo delta correspondente. Se não existe, uma nova
        linha 9900 é inserida antes do 9990.
        """
        preamble: list[str] = []
        nine_900_order: list[str] = []
        nine_900_qty: dict[str, int] = {}
        nine_990_raw: str | None = None
        nine_999_raw: str | None = None

        for raw in raw_lines:
            fields = _split(raw)
            reg = fields[1] if len(fields) > 1 else ""

            if reg == "9001":
                preamble.append(raw)
            elif reg == "9900" and len(fields) > 3:
                rec_type = fields[2]
                qty = int(fields[3]) if fields[3].isdigit() else 0
                nine_900_order.append(rec_type)
                nine_900_qty[rec_type] = qty
            elif reg == "9990":
                nine_990_raw = raw
            elif reg == "9999":
                nine_999_raw = raw

        # Aplica deltas às entradas existentes
        orig_types = set(nine_900_qty.keys())
        for rec_type, delta in net_counts.items():
            if rec_type in nine_900_qty:
                nine_900_qty[rec_type] = max(0, nine_900_qty[rec_type] + delta)
            elif delta > 0:
                nine_900_qty[rec_type] = delta
                nine_900_order.append(rec_type)

        # Novos tipos de registro que precisam de entrada 9900 nova
        new_types = [t for t in net_counts if t not in orig_types and net_counts[t] > 0]
        new_9900_count = len(new_types)

        # A própria entrada "9900" no 9900 reflete as novas linhas 9900 adicionadas
        if "9900" in nine_900_qty:
            nine_900_qty["9900"] = nine_900_qty["9900"] + new_9900_count

        # Monta saída
        output: list[str] = list(preamble)

        for rec_type in nine_900_order:
            output.append(build_pipe_record("9900", rec_type, str(nine_900_qty[rec_type])))

        # 9990: conta de linhas no bloco 9 (incluindo novas linhas 9900)
        if nine_990_raw:
            fields = _split(nine_990_raw)
            orig_9990 = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 0
            output.append(build_pipe_record("9990", str(orig_9990 + new_9900_count)))

        # 9999: contagem total de linhas no arquivo
        if nine_999_raw:
            fields = _split(nine_999_raw)
            orig_9999 = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 0
            output.append(build_pipe_record("9999", str(orig_9999 + total_additions + new_9900_count)))

        return output
