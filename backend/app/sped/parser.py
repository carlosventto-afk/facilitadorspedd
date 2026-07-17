"""
SPED EFD ICMS/IPI — Parser de arquivo por streaming (dois passes).

Pass 1 (indexação): lê linha a linha e constrói SpedIndex com metadados.
                    Apenas strings de chave são mantidas em memória.
Pass 2 (escrita): feito pelo SpedEnricher em writer.py.

Referência de layout: Guia Prático EFD ICMS/IPI v3.1.8 (SEFAZ).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from app.sped.codigos_ajuste import CODIGOS
from app.sped.formatter import parse_decimal
from app.sped.models import C100Block, SpedIndex, SpedLine

logger = logging.getLogger(__name__)

# Registros que são filhos diretos de C100 (afetam last_child_line)
_C100_CHILDREN = frozenset({"C105", "C110", "C111", "C112", "C113", "C114",
                              "C115", "C116", "C120", "C130", "C140", "C141",
                              "C160", "C165", "C170", "C171", "C172", "C173",
                              "C174", "C175", "C176", "C177", "C178", "C179",
                              "C180", "C181", "C185", "C186", "C190", "C191",
                              "C195", "C197", "C198", "C199"})

# Qualquer registro que NÃO seja filho de C100 indica fim do bloco C100 atual
_C_BLOCK_NON_CHILDREN = frozenset({"C001", "C100", "C990"})

# Códigos de ajuste/receita que o motor usa para antecipação (ver
# codigos_ajuste.CODIGOS) — usados para identificar C197/E111/E116 de
# antecipação já existentes no SPED original, que devem ser descartados e
# relançados a partir da planilha SEFA-PA (fonte única de verdade).
_ANTECIPACAO_C197_CODES = frozenset(c.c197 for c in CODIGOS.values())
_ANTECIPACAO_E111_CODES = frozenset(c.e111 for c in CODIGOS.values() if c.e111)
_ANTECIPACAO_E116_COD_REC = frozenset(c.cod_receita_e116 for c in CODIGOS.values())


def _split_line(raw: str) -> list[str]:
    """Divide uma linha SPED pelo separador |. Remove quebra de linha."""
    return raw.rstrip("\r\n").split("|")


def _parse_line(line_number: int, raw: str) -> SpedLine:
    fields = _split_line(raw)
    registro = fields[1] if len(fields) > 1 else ""
    return SpedLine(line_number=line_number, raw=raw, registro=registro, fields=fields)


class SpedParser:
    """
    Primeiro passo: indexa o arquivo SPED sem carregar tudo na memória.

    Constrói SpedIndex com:
    - participant_map: COD_PART → CNPJ (de registros 0150)
    - c100_blocks: lista de C100Block com posições e metadados de cada NF
    - e110_line, e111_entries, e116_entries: posições dos registros do Bloco E
    - total_lines: número total de linhas (necessário para Pass 2)
    """

    def parse(self, path: Path) -> SpedIndex:
        participant_map: dict[str, str] = {}
        c100_blocks: list[C100Block] = []
        e110_line: int | None = None
        e111_entries: list[tuple[int, str]] = []
        e116_entries: list[tuple[int, str, str]] = []
        e_block_end_line: int | None = None
        dt_ini: str = ""
        dt_fim: str = ""
        existing_0460_codes: set[str] = set()
        c195_cod_obs_by_line: dict[int, str] = {}
        antecipacao_strip_lines: set[int] = set()
        antecipacao_stripped_e111_total = Decimal("0")
        antecipacao_stripped_e116_total = Decimal("0")

        current_c100: C100Block | None = None
        prev_reg: str = ""
        prev_line_number: int = -1

        with path.open(encoding="latin-1") as f:
            for line_number, raw in enumerate(f):
                sl = _parse_line(line_number, raw)
                reg = sl.registro

                # ── Bloco 0: período, participantes e observações ─────────────
                if reg == "0000" and len(sl.fields) > 5:
                    # |0000|COD_VER|COD_FIN|DT_INI|DT_FIN|CNPJ|...
                    dt_ini = sl.fields[4]
                    dt_fim = sl.fields[5]

                elif reg == "0150":
                    # |0150|COD_PART|NOME|COD_PAIS|CNPJ|CPF|IE|COD_MUN|...
                    if len(sl.fields) > 5:
                        cod_part = sl.fields[2]
                        cnpj = sl.fields[5].strip().replace(".", "").replace("/", "").replace("-", "")
                        if cod_part and cnpj:
                            participant_map[cod_part] = cnpj

                elif reg == "0460":
                    # |0460|COD_OBS|TXT| — tabela de observações (pai dos C195/C197)
                    if len(sl.fields) > 2:
                        existing_0460_codes.add(sl.fields[2].strip())

                # ── Bloco C: notas fiscais ─────────────────────────────────────
                elif reg == "C100":
                    # Fecha bloco anterior se existir
                    if current_c100 is not None:
                        current_c100.line_end = line_number
                        c100_blocks.append(current_c100)

                    # |C100|IND_OPER|IND_EMIT|COD_PART|COD_MOD|COD_SIT|SER|NUM_DOC|CHV_NFE|...
                    f_list = sl.fields
                    current_c100 = C100Block(
                        line_start=line_number,
                        line_end=line_number + 1,  # será sobrescrito
                        chave_nfe=f_list[9].strip() if len(f_list) > 9 else "",
                        numero_nf=f_list[8].strip() if len(f_list) > 8 else "",
                        serie=f_list[7].strip() if len(f_list) > 7 else "",
                        cod_part=f_list[4].strip() if len(f_list) > 4 else "",
                        ind_oper=f_list[2].strip() if len(f_list) > 2 else "",
                        last_child_line=line_number,  # starts at C100 itself
                    )

                elif reg in _C100_CHILDREN and current_c100 is not None:
                    current_c100.last_child_line = line_number
                    if reg == "C195":
                        # Guarda o COD_OBS de todo C195 (independente de ser de
                        # antecipação ou não) para depois decidir, já sabendo
                        # quais linhas foram removidas, se o 0460 correspondente
                        # ficou órfão (ver existing_0460_still_referenced abaixo).
                        c195_cod_obs_by_line[line_number] = (
                            sl.fields[2].strip() if len(sl.fields) > 2 else ""
                        )
                    elif reg == "C197":
                        # C197 de antecipação (código conhecido) já existente:
                        # marca para remoção — a planilha SEFA-PA é relançada do
                        # zero, não reconciliada com o que já está no arquivo.
                        cod = sl.fields[2].strip() if len(sl.fields) > 2 else ""
                        if cod in _ANTECIPACAO_C197_CODES:
                            antecipacao_strip_lines.add(line_number)
                            if prev_reg == "C195":
                                antecipacao_strip_lines.add(prev_line_number)

                elif reg in _C_BLOCK_NON_CHILDREN and current_c100 is not None:
                    # Fecha o bloco C100 atual
                    current_c100.line_end = line_number
                    c100_blocks.append(current_c100)
                    current_c100 = None

                # ── Bloco E: apuração ──────────────────────────────────────────
                elif reg == "E110":
                    e110_line = line_number

                elif reg == "E111":
                    if len(sl.fields) > 2:
                        cod = sl.fields[2].strip()
                        e111_entries.append((line_number, cod))
                        # E111 de antecipação (ex.: PA020008) já existente: marca
                        # para remoção e acumula o valor para ajustar o delta do
                        # E110 (o campo lá reflete o valor antigo, que está saindo)
                        if cod in _ANTECIPACAO_E111_CODES:
                            antecipacao_strip_lines.add(line_number)
                            antecipacao_stripped_e111_total += (
                                parse_decimal(sl.fields[4]) if len(sl.fields) > 4 else Decimal("0")
                            )

                elif reg == "E116":
                    # |E116|COD_OR|VL_OR|DT_VCTO|COD_REC|...
                    cod_or = sl.fields[2].strip() if len(sl.fields) > 2 else ""
                    cod_rec = sl.fields[5].strip() if len(sl.fields) > 5 else ""
                    e116_entries.append((line_number, cod_or, cod_rec))
                    # E116 de antecipação (COD_REC conhecido) já existente: marca
                    # para remoção e acumula o valor para ajustar o delta do E110
                    if cod_rec in _ANTECIPACAO_E116_COD_REC:
                        antecipacao_strip_lines.add(line_number)
                        antecipacao_stripped_e116_total += (
                            parse_decimal(sl.fields[3]) if len(sl.fields) > 3 else Decimal("0")
                        )

                elif reg == "E990":
                    e_block_end_line = line_number

                prev_reg = reg
                prev_line_number = line_number

        # Fecha o último bloco C100 se o arquivo terminar sem C990
        if current_c100 is not None:
            current_c100.line_end = line_number + 1
            c100_blocks.append(current_c100)

        total_lines = line_number + 1 if 'line_number' in dir() else 0

        # COD_OBS ainda referenciado por pelo menos um C195 que sobrevive (ou
        # seja, cuja linha não está em antecipacao_strip_lines). Um 0460
        # existente cujo código não aparece aqui ficou órfão — o C195 que o
        # referenciava foi removido junto com o C197 de antecipação antigo.
        existing_0460_still_referenced: set[str] = {
            cod_obs
            for line_num, cod_obs in c195_cod_obs_by_line.items()
            if cod_obs and line_num not in antecipacao_strip_lines
        }

        logger.info(
            "Indexação concluída: %d NFs, E110 na linha %s, %d E111, %d E116, "
            "%d registro(s) de antecipação pré-existente a descartar",
            len(c100_blocks), e110_line, len(e111_entries), len(e116_entries),
            len(antecipacao_strip_lines),
        )

        return SpedIndex(
            participant_map=participant_map,
            c100_blocks=c100_blocks,
            e110_line=e110_line,
            e111_entries=e111_entries,
            e116_entries=e116_entries,
            e_block_end_line=e_block_end_line,
            antecipacao_strip_lines=antecipacao_strip_lines,
            antecipacao_stripped_e111_total=antecipacao_stripped_e111_total,
            antecipacao_stripped_e116_total=antecipacao_stripped_e116_total,
            total_lines=total_lines,
            dt_ini=dt_ini,
            dt_fim=dt_fim,
            existing_0460_codes=existing_0460_codes,
            existing_0460_still_referenced=existing_0460_still_referenced,
        )


def resolve_cnpj(cod_part: str, participant_map: dict[str, str]) -> str | None:
    """Retorna o CNPJ do participante ou None se não encontrado."""
    return participant_map.get(cod_part)
