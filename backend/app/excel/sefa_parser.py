"""
Parser da planilha de antecipações de ICMS da SEFA-PA.

Suporta dois formatos de "Detalhamento de Classificação de Receita":

  Formato A (produto a produto, 20+ colunas):
    L0: Título com "EMPRESA: ... Receita: COD1173 ICMS ANTECIPADO ESPECIAL"
    L1: Cabeçalho com colunas "NF", "CNPJ ORIGEM", "DANFE", "TOTAL ESTORNO"
    L2+: Uma linha por produto (mesmo NF pode ter várias linhas)
    → valor por NF = soma de "TOTAL ESTORNO"

  Formato B (nota a nota, ~13 colunas):
    L0: Título com "Receita: 1173 - Antecipado Especial"
    L1: Cabeçalho com "SERIE / NOTA", "CNPJ", "ICMS A PAGAR", "DANFE"
    L2+: Uma linha por produto/NF
    → valor por NF = soma de "ICMS A PAGAR"

Regras de negócio:
  - O TIPO de antecipação vem do título (linha 0): 1146/1173/1152
  - Múltiplas linhas do mesmo DANFE são SOMADAS num único RawAnticipation
  - Linhas com DANFE vazio ou valor <= 0 são ignoradas
  - Aceita .xlsx (openpyxl) e .xls (pandas+xlrd)
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Mapeamento de pistas de tipo de antecipação → tipo canônico ─────────────
_TIPO_HINTS = {
    "1146": "NORMAL",
    "cod1146": "NORMAL",
    "normal": "NORMAL",
    "antecipado normal": "NORMAL",
    "1152": "CESTA_BASICA",
    "cod1152": "CESTA_BASICA",
    "cesta": "CESTA_BASICA",
    "1173": "ESPECIAL",
    "cod1173": "ESPECIAL",
    "especial": "ESPECIAL",
    "antecipado especial": "ESPECIAL",
}

# Mapeamento de nome de coluna → (campo interno, prioridade)
# Maior prioridade vence quando múltiplas colunas mapeiam para o mesmo campo.
# Prioridade 10=melhor, 1=pior fallback.
_COL_MAP: dict[str, tuple[str, int]] = {
    # Chave NF-e
    "danfe": ("chave_nfe", 10),
    "chave de acesso": ("chave_nfe", 9),
    "chave nfe": ("chave_nfe", 8),
    "chave_nfe": ("chave_nfe", 8),
    "chave": ("chave_nfe", 5),
    # Número da NF
    "nf": ("numero_nf", 10),
    "num_doc": ("numero_nf", 9),
    "num doc": ("numero_nf", 9),
    "numero nf": ("numero_nf", 8),
    "numero": ("numero_nf", 5),
    # Série/Nota combinado (ex: "1/27146")
    "serie / nota": ("serie_nota", 10),
    "serie/nota": ("serie_nota", 10),
    # CNPJ do emitente
    "cnpj origem": ("emitente_cnpj", 10),
    "cnpj emit": ("emitente_cnpj", 9),
    "cnpj emitente": ("emitente_cnpj", 9),
    "cnpj": ("emitente_cnpj", 5),
    # Valor a pagar/registrar no C197 — prioridade decrescente
    "total estorno": ("valor_icms", 10),   # formato A (por produto, crédito)
    "icms a pagar": ("valor_icms", 10),    # formato B (por nota, pagamento)
    "expectativa a pagar": ("valor_icms", 6),
    "icms do produto": ("valor_icms", 4),
    "valor icms calc": ("valor_icms", 3),
    "valor icms": ("valor_icms", 2),
    # Série (formato B com coluna separada)
    "serie": ("serie", 5),
}


def _normalize_header_cell(cell: object) -> str:
    if cell is None:
        return ""
    return (
        str(cell)
        .lower()
        .strip()
        .replace("\n", " ")
        .replace("  ", " ")
        .replace("nº", "n")
    )


def _extract_tipo_from_title(title_row: list) -> str:
    """Extrai o tipo de antecipação do título (linha 0 da planilha)."""
    text = " ".join(str(v).lower() for v in title_row if v is not None)
    for hint, tipo in _TIPO_HINTS.items():
        if hint in text:
            return tipo
    raise ValueError(
        f"Tipo de antecipação não identificado no título da planilha. "
        f"Esperado: 1146, 1173 ou 1152. Título: {text[:200]!r}"
    )


def _map_columns(header_row: list) -> dict[int, str]:
    """
    Mapeia índices de colunas do cabeçalho para campos internos.

    Quando múltiplas colunas mapeiam para o mesmo campo, vence a de maior prioridade.
    """
    # col_idx → (field, priority)
    best: dict[str, tuple[int, int]] = {}   # field → (col_idx, priority)

    for i, cell in enumerate(header_row):
        key = _normalize_header_cell(cell)
        if not key:
            continue
        # Tentativa exata
        if key in _COL_MAP:
            field, prio = _COL_MAP[key]
            if field not in best or prio > best[field][1]:
                best[field] = (i, prio)
            continue
        # Tentativa por substring (usa maior prioridade do fragmento encontrado)
        for fragment, (field, prio) in _COL_MAP.items():
            if fragment in key:
                if field not in best or prio > best[field][1]:
                    best[field] = (i, prio)
                break

    return {col_idx: field for field, (col_idx, _) in best.items()}


def _is_valid_chave(chave: object) -> bool:
    s = re.sub(r"\D", "", str(chave or ""))
    return len(s) == 44


def _clean_cnpj(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip().replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_serie_nota(value: object) -> tuple[str, str]:
    """Parseia 'SERIE / NOTA' no formato '1/27146' → (serie, numero)."""
    s = str(value or "").strip()
    if "/" in s:
        parts = s.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return "1", s


def _load_rows_from_excel(path: Path) -> list[list]:
    """Lê todas as linhas da primeira aba como lista de listas."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        try:
            import pandas as pd
            df = pd.read_excel(str(path), sheet_name=0, header=None, dtype=str)
            return [list(row) for _, row in df.iterrows()]
        except ImportError:
            raise ImportError(
                "xlrd não instalado. Execute: pip install xlrd>=2.0.1"
            )
    else:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            ws = wb.active
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            wb.close()
            return rows
        except ImportError:
            raise ImportError("openpyxl não instalado.")


def parse_sefa_excel(path: Path):
    """
    Lê a planilha de antecipações da SEFA-PA e retorna lista de RawAnticipation.

    Aceita Formato A (produto a produto) e Formato B (nota a nota).
    Agrega múltiplas linhas do mesmo DANFE em um único registro.

    Retorna lista de RawAnticipation (importado de app.sped.matcher).
    """
    # Import tardio para evitar dependência circular
    from app.sped.matcher import RawAnticipation

    rows = _load_rows_from_excel(path)
    if len(rows) < 2:
        raise ValueError("Planilha vazia ou sem dados.")

    # Linha 0: título — extrai o tipo de antecipação
    tipo = _extract_tipo_from_title(rows[0])
    logger.info("Tipo de antecipação detectado: %s", tipo)

    # Encontra a linha de cabeçalho (primeira linha com coluna "danfe" ou similar)
    header_row_idx = None
    col_map: dict[int, str] = {}
    for i, row in enumerate(rows[1:], 1):
        cm = _map_columns(row)
        if "chave_nfe" in cm.values():
            header_row_idx = i
            col_map = cm
            break

    if header_row_idx is None:
        raise ValueError(
            "Cabeçalho não encontrado na planilha. "
            "Coluna DANFE/chave_nfe não identificada."
        )

    logger.info(
        "Cabeçalho na linha %d. Colunas mapeadas: %s",
        header_row_idx + 1,
        {v: k for k, v in col_map.items()},
    )

    # Agrupa por chave_nfe: {chave_nfe → {emitente_cnpj, numero_nf, serie, valor_total}}
    aggregated: dict[str, dict] = {}

    for row_idx, row in enumerate(rows[header_row_idx + 1:], header_row_idx + 1):
        if not row or all(v is None or str(v).strip() in ("", "nan") for v in row):
            continue

        # Lê valor para cada campo pelo índice da coluna
        raw: dict[str, object] = {}
        for col_idx, field in col_map.items():
            if col_idx < len(row):
                raw[field] = row[col_idx]

        # chave_nfe (DANFE) — obrigatório para match
        chave_raw = raw.get("chave_nfe", "")
        chave = re.sub(r"\D", "", str(chave_raw or ""))
        if len(chave) != 44:
            continue  # linha sem DANFE válido → pula (ex: linha de total/subtotal)

        # Valor do ICMS desta linha
        valor = _to_decimal(raw.get("valor_icms"))
        if valor <= 0:
            continue

        # CNPJ emitente — pode estar na coluna ou extraído da chave NF-e (pos 3-16)
        cnpj = _clean_cnpj(raw.get("emitente_cnpj"))
        if not cnpj and len(chave) == 44:
            cnpj = chave[6:20]   # CNPJ é o bloco 6-19 da chave NF-e

        # Número e série da NF
        if "serie_nota" in raw:
            serie, numero_nf = _parse_serie_nota(raw["serie_nota"])
        else:
            serie = str(raw.get("serie", "1")).strip() or "1"
            numero_nf = str(raw.get("numero_nf", "")).strip()
            if not numero_nf and len(chave) == 44:
                # Extrai número da chave NF-e (pos 25-33)
                numero_nf = str(int(chave[25:34]))

        # Acumula por chave NF-e
        if chave not in aggregated:
            aggregated[chave] = {
                "chave_nfe": chave,
                "emitente_cnpj": cnpj,
                "numero_nf": numero_nf,
                "serie": serie,
                "valor_icms": Decimal("0"),
            }
        aggregated[chave]["valor_icms"] += valor

    # Converte para RawAnticipation
    results: list[RawAnticipation] = []
    for chave, data in aggregated.items():
        if data["valor_icms"] <= 0:
            continue
        results.append(RawAnticipation(
            chave_nfe=chave,
            numero_nf=data["numero_nf"],
            serie=data["serie"],
            emitente_cnpj=data["emitente_cnpj"],
            tipo=tipo,
            valor_icms=data["valor_icms"],
            dare_numero=None,       # SEFA-PA não inclui número do DARE/DAR
            dare_vencimento=None,   # Preenchido pelo contador no E116
        ))

    if not results:
        raise ValueError(
            "Nenhuma antecipação com valor > 0 encontrada na planilha. "
            "Verifique a coluna de valor (TOTAL ESTORNO / ICMS A PAGAR)."
        )

    logger.info(
        "Planilha SEFA-PA: %d NF(s) únicas | Tipo: %s | Total ICMS: %s",
        len(results),
        tipo,
        sum(r.valor_icms for r in results),
    )
    return results
