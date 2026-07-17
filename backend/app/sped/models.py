"""Dataclasses for SPED EFD ICMS/IPI parsing."""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class SpedLine:
    line_number: int
    raw: str                  # original line including newline
    registro: str             # e.g. "C100"
    fields: list[str]         # split by '|'; index 0 is empty, index 1 is registro


@dataclass
class C100Block:
    line_start: int           # line number of the C100 record itself
    line_end: int             # exclusive — line number of next C100 or C990
    chave_nfe: str            # CHV_NFE field from C100 (44 chars or empty)
    numero_nf: str            # NUM_DOC field
    serie: str                # SER field
    cod_part: str             # COD_PART (maps to CNPJ via 0150)
    ind_oper: str             # "0"=entrada "1"=saída
    last_child_line: int      # last line of C190/C195/C197 within this block


@dataclass
class SpedIndex:
    """Result of the first pass over the SPED file."""
    participant_map: dict[str, str]          # cod_part → cnpj (14 digits)
    c100_blocks: list[C100Block]
    e110_line: int | None                    # line number of E110 record
    e111_entries: list[tuple[int, str]]      # (line_number, cod_aj_apur)
    e116_entries: list[tuple[int, str, str]]  # (line_number, cod_or, cod_rec) of existing E116 records
    e_block_end_line: int | None             # line number of E990 (to inject E116 before it)
    total_lines: int
    dt_ini: str = ""                         # DDMMAAAA from 0000 record (competência início)
    dt_fim: str = ""                         # DDMMAAAA from 0000 record (competência fim)
    existing_0460_codes: set[str] = field(default_factory=set)  # COD_OBS já cadastrados no bloco 0
    # COD_OBS de existing_0460_codes que ainda é referenciado por pelo menos um
    # C195 que sobrevive à remoção de antecipação pré-existente. Um código em
    # existing_0460_codes que NÃO está aqui ficou órfão (seu único C195 foi
    # removido junto do C197 de antecipação antigo) e o 0460 correspondente
    # deve ser removido também — senão o PVA acusa "COD_OBS não referenciado".
    existing_0460_still_referenced: set[str] = field(default_factory=set)
    # Linhas de C195/C197/E111/E116 de antecipação (códigos conhecidos em
    # codigos_ajuste.CODIGOS) já existentes no SPED original. A planilha
    # SEFA-PA é a única fonte de verdade: esses registros são removidos e
    # relançados do zero a partir dela, em vez de reconciliados/mesclados —
    # dado pré-existente pode estar errado ou incompleto (ex.: NF com 2 itens
    # onde só 1 tinha C197 lançado).
    antecipacao_strip_lines: set[int] = field(default_factory=set)
    antecipacao_stripped_e111_total: Decimal = Decimal("0")  # soma do VL_AJ removido
    antecipacao_stripped_e116_total: Decimal = Decimal("0")  # soma do VL_OR removido


@dataclass
class MatchedAnticipation:
    """An anticipation record from Excel that was matched to a C100 block."""
    c100_block: C100Block
    chave_nfe: str
    numero_nf: str
    serie: str
    emitente_cnpj: str
    tipo: str                  # "NORMAL" | "ESPECIAL" | "CESTA_BASICA"
    valor_icms: Decimal
    dare_numero: str | None
    dare_vencimento: str | None   # DDMMAAAA format
    codigo_ajuste_c197: str       # e.g. PA70000010
    codigo_ajuste_e111: str | None
    cod_receita_e116: str         # e.g. 1146


@dataclass
class ProcessingResult:
    c197_inserted: int = 0
    e111_inserted: int = 0
    e116_inserted: int = 0
    nfs_found: int = 0
    anticipations_total: int = 0
    anticipations_matched: int = 0
    anticipations_unmatched: list[str] = field(default_factory=list)
    total_icms_value: Decimal = Decimal("0")
