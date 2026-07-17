"""
Funções de formatação e parsing de valores no padrão SPED EFD.

SPED usa vírgula como separador decimal e sem separador de milhar.
Exemplo: R$ 1.234,56 → "1234,56" no arquivo SPED.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def parse_decimal(value: str) -> Decimal:
    """Converte string SPED ("1234,56") para Decimal."""
    if not value or value.strip() == "":
        return Decimal("0")
    cleaned = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal("0")


def format_decimal(value: Decimal, decimals: int = 2) -> str:
    """Converte Decimal para string SPED ("1234,56")."""
    quantized = value.quantize(Decimal(f"0.{'0' * decimals}"), rounding=ROUND_HALF_UP)
    return str(quantized).replace(".", ",")


def format_date_sped(date_str: str) -> str:
    """
    Normaliza data para formato SPED (DDMMAAAA).
    Aceita: DDMMAAAA, DD/MM/AAAA, AAAA-MM-DD.
    """
    clean = date_str.replace("/", "").replace("-", "").strip()
    if len(clean) == 8:
        if clean[:4].isdigit() and int(clean[:4]) > 1900:
            # Pode ser AAAAMMDD — inverte para DDMMAAAA
            year, month, day = clean[:4], clean[4:6], clean[6:8]
            return day + month + year
        return clean  # já está em DDMMAAAA
    return clean


def build_pipe_record(*fields: str) -> str:
    """Constrói uma linha SPED: |CAMPO1|CAMPO2|...|\\n"""
    return "|" + "|".join(fields) + "|\n"


def get_e110_field_index(field_name: str) -> int:
    """
    Retorna o índice (0-based dentro dos campos de conteúdo, após 'E110') do campo E110.

    Estrutura E110 (Guia Prático EFD ICMS/IPI v3.1.8):
    Num  Campo                  Índice (após split por |, contando do 0)
     01  REG                    1
     02  VL_TOT_DEBITOS         2
     03  VL_AJ_DEBITOS          3
     04  VL_TOT_AJ_DEBITOS      4
     05  VL_ESTORNOS_CRED       5
     06  VL_TOT_CREDITOS        6
     07  VL_AJ_CREDITOS         7
     08  VL_TOT_AJ_CREDITOS     8
     09  VL_ESTORNOS_DEB        9
     10  VL_SLD_CREDOR_ANT      10
     11  VL_SLD_APURADO         11
     12  VL_TOT_DED             12
     13  VL_ICMS_RECOLHER       13
     14  VL_SLD_CREDOR_TRANSP   14
     15  VL_EXPORTACOES         15
     16  VL_DEB_ESP             16
    """
    E110_FIELDS = {
        "VL_TOT_DEBITOS": 2,
        "VL_AJ_DEBITOS": 3,
        "VL_TOT_AJ_CREDITOS": 4,
        "VL_ESTORNOS_CRED": 5,
        "VL_TOT_CREDITOS": 6,
        "VL_AJ_CREDITOS": 7,
        "VL_TOT_AJ_CREDITOS_2": 8,
        "VL_ESTORNOS_DEB": 9,
        "VL_SLD_CREDOR_ANT": 10,
        "VL_SLD_APURADO": 11,
        "VL_TOT_DED": 12,
        "VL_ICMS_RECOLHER": 13,
        "VL_SLD_CREDOR_TRANSP": 14,
        "VL_EXPORTACOES": 15,
        "VL_DEB_ESP": 16,
    }
    return E110_FIELDS[field_name]


# Índice do campo VL_DEB_ESP no array de fields após split por '|'
E110_VL_DEB_ESP_IDX = 16   # campos: [empty, E110, f2, f3, ..., f16_VL_DEB_ESP]
E110_VL_AJ_CREDITOS_IDX = 7
