"""
Funções de normalização de valores lidos da planilha SEFA-PA.

A planilha pode conter CNPJ formatado, decimais com vírgula, datas em
formatos variados, e strings de tipo de antecipação com capitalização
e acentos variáveis.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


# ── CNPJ ─────────────────────────────────────────────────────────────────────

_CNPJ_DIGITS = re.compile(r"\D")


def clean_cnpj(value: object) -> str:
    """Remove pontuação e retorna apenas os 14 dígitos do CNPJ."""
    if value is None:
        return ""
    return _CNPJ_DIGITS.sub("", str(value))


def is_valid_cnpj(cnpj: str) -> bool:
    """Valida dígitos verificadores do CNPJ."""
    if len(cnpj) != 14 or not cnpj.isdigit():
        return False
    if cnpj == cnpj[0] * 14:
        return False

    def _calc(digits: str, weights: list[int]) -> int:
        total = sum(int(d) * w for d, w in zip(digits, weights))
        rem = total % 11
        return 0 if rem < 2 else 11 - rem

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _calc(cnpj[:12], w1)
    d2 = _calc(cnpj[:13], w2)
    return cnpj[12] == str(d1) and cnpj[13] == str(d2)


# ── Tipo de Antecipação ───────────────────────────────────────────────────────

_TIPO_KEYWORDS = {
    "ESPECIAL": ["especial"],
    "CESTA_BASICA": ["cesta", "basica", "básica", "1152"],
    "NORMAL": ["normal", "1146", "art. 107", "art.107"],
}


def normalize_tipo(value: object) -> str:
    """
    Normaliza o tipo de antecipação para um dos valores canônicos:
    "NORMAL", "ESPECIAL" ou "CESTA_BASICA".

    Lança ValueError se não conseguir identificar o tipo.
    """
    if value is None:
        raise ValueError("Tipo de antecipação ausente")
    raw = str(value).lower().strip()
    # Remoção de acentos simplificada
    raw = raw.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    raw = raw.replace("ã", "a").replace("õ", "o").replace("â", "a").replace("ê", "e")

    # CESTA_BASICA antes de NORMAL para evitar falso match em strings como
    # "ANTECIPADO CESTA BASICA NORMAL"
    for tipo, keywords in _TIPO_KEYWORDS.items():
        for kw in keywords:
            if kw in raw:
                return tipo

    raise ValueError(f"Tipo de antecipação não reconhecido: '{value}'")


# ── Decimais ─────────────────────────────────────────────────────────────────

def parse_decimal_excel(value: object) -> Decimal:
    """
    Converte valor lido do Excel para Decimal.

    Aceita: float (nativo do Excel), string com ',' ou '.', int.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    # String: pode ser "1.234,56" (BR) ou "1,234.56" (EN)
    s = str(value).strip()
    if "," in s and "." in s:
        # Descobre qual é o separador decimal pelo que aparece por último
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Valor decimal inválido: '{value}'")


# ── Datas ─────────────────────────────────────────────────────────────────────

import datetime


def normalize_date_to_sped(value: object) -> str:
    """
    Converte data para formato DDMMAAAA (padrão SPED).

    Aceita: datetime.datetime, datetime.date, string DDMMAAAA, DD/MM/AAAA,
    AAAA-MM-DD, AAAA/MM/DD.
    Retorna "" se não conseguir parsear.
    """
    if value is None:
        return ""

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d%m%Y")

    s = str(value).strip()
    if not s:
        return ""

    # Tenta vários formatos de string
    for fmt in ("%d/%m/%Y", "%d%m%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%d%m%Y")
        except ValueError:
            continue

    return s  # retorna como veio, o validador posterior detectará o erro


# ── Chave NF-e ────────────────────────────────────────────────────────────────

_NFE_KEY_STRIP = re.compile(r"[^0-9]")


def normalize_chave_nfe(value: object) -> str:
    """Remove espaços e não-dígitos. Retorna '' se não tiver 44 dígitos."""
    if value is None:
        return ""
    clean = _NFE_KEY_STRIP.sub("", str(value))
    return clean if len(clean) == 44 else ""


# ── Número da NF ──────────────────────────────────────────────────────────────

def normalize_numero_nf(value: object) -> str:
    """Converte número da NF para string sem zeros à esquerda desnecessários."""
    if value is None:
        return ""
    if isinstance(value, float):
        value = int(value)
    return str(value).strip().lstrip("0") or "0"


# ── Série da NF ───────────────────────────────────────────────────────────────

def normalize_serie(value: object) -> str:
    if value is None:
        return "1"
    s = str(value).strip()
    return s if s else "1"
