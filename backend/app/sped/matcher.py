"""
Associa registros de antecipação (do Excel) aos blocos C100 do SPED.

Estratégia de match (ordem de prioridade):
  1. Chave NF-e de 44 dígitos (global e única)
  2. Fallback: (cnpj_emitente, numero_nf, serie)

Registros sem match são retornados como lista de chaves não encontradas.

A planilha SEFA-PA é a única fonte de verdade para o valor de cada NF: todo
C197/E111/E116 de antecipação pré-existente no SPED é descartado pelo
SpedEnricher (writer.py) e relançado do zero a partir do que vem aqui — não
há reconciliação de valor parcial neste módulo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from app.sped.codigos_ajuste import get_codigo
from app.sped.models import C100Block, MatchedAnticipation, SpedIndex
from app.sped.formatter import format_date_sped
from app.sped.parser import resolve_cnpj

logger = logging.getLogger(__name__)


@dataclass
class RawAnticipation:
    """Representação normalizada de uma linha da planilha SEFA-PA."""
    chave_nfe: str        # 44 chars (pode ser vazio em NFs antigas)
    numero_nf: str
    serie: str
    emitente_cnpj: str    # 14 dígitos, sem formatação
    tipo: str             # "NORMAL" | "ESPECIAL" | "CESTA_BASICA"
    valor_icms: Decimal
    dare_numero: str | None
    dare_vencimento: str | None  # DDMMAAAA


def match_anticipations(
    index: SpedIndex,
    anticipations: list[RawAnticipation],
) -> tuple[list[MatchedAnticipation], list[RawAnticipation]]:
    """
    Retorna (matched, unmatched).

    matched: lista de MatchedAnticipation com referência ao C100Block correto.
    unmatched: antecipações que não encontraram NF correspondente no SPED.
    """
    # Indexar os blocos C100 para lookup rápido
    by_chave: dict[str, C100Block] = {}
    by_fallback: dict[tuple[str, str, str], C100Block] = {}

    for block in index.c100_blocks:
        if block.ind_oper != "0":
            continue  # só notas de entrada (antecipação é sempre na entrada)

        if block.chave_nfe:
            clean_chave = block.chave_nfe.replace(" ", "")
            by_chave[clean_chave] = block

        cnpj = resolve_cnpj(block.cod_part, index.participant_map) or ""
        key = (cnpj, block.numero_nf.lstrip("0"), block.serie)
        by_fallback[key] = block

    matched: list[MatchedAnticipation] = []
    unmatched: list[RawAnticipation] = []

    for ant in anticipations:
        block: C100Block | None = None

        # Tentativa 1: chave NF-e
        if ant.chave_nfe:
            block = by_chave.get(ant.chave_nfe.replace(" ", ""))

        # Tentativa 2: fallback por CNPJ + número + série
        if block is None:
            key = (ant.emitente_cnpj, ant.numero_nf.lstrip("0"), ant.serie)
            block = by_fallback.get(key)

        if block is None:
            logger.warning(
                "Antecipação sem match: NF %s série %s CNPJ %s",
                ant.numero_nf, ant.serie, ant.emitente_cnpj,
            )
            unmatched.append(ant)
            continue

        codigo = get_codigo(ant.tipo)
        vencimento = format_date_sped(ant.dare_vencimento) if ant.dare_vencimento else ""

        # Sempre lança o valor cheio da planilha — qualquer C197/E111/E116 de
        # antecipação já existente para essa NF é descartado pelo writer.py,
        # então não há valor "já coberto" a subtrair aqui.
        matched.append(MatchedAnticipation(
            c100_block=block,
            chave_nfe=ant.chave_nfe,
            numero_nf=ant.numero_nf,
            serie=ant.serie,
            emitente_cnpj=ant.emitente_cnpj,
            tipo=ant.tipo,
            valor_icms=ant.valor_icms,
            dare_numero=ant.dare_numero,
            dare_vencimento=vencimento,
            codigo_ajuste_c197=codigo.c197,
            codigo_ajuste_e111=codigo.e111,
            cod_receita_e116=codigo.cod_receita_e116,
        ))

    logger.info(
        "Match: %d antecipações encontradas, %d não encontradas",
        len(matched), len(unmatched),
    )
    return matched, unmatched
