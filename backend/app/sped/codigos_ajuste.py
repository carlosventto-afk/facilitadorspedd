"""
Mapeamento de tipos de antecipação de ICMS → códigos de ajuste SEFA-PA.

Fonte: Orientações de Escrituração SEFA-PA (Documentos 1146, 1173, 1152)
e Tabelas 5.1.1 e 5.3 do Guia Prático EFD ICMS/IPI.

IMPORTANTE: Qualquer alteração aqui deve ser validada contra os PDFs
na pasta Legislação/ e confirmada com especialista contábil antes de
ir para produção.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CodigoAjuste:
    # Código para o registro C197 (Tabela 5.3 — ajuste de documento fiscal)
    c197: str
    # Código de apuração para E111 (Tabela 5.1.1 — ajuste da apuração do ICMS)
    # None = este tipo não gera E111
    e111: str | None
    # Código de receita estadual para E116 (Tabela 5.4)
    cod_receita_e116: str
    # Descrição para uso em DESCR_COMPL_AJ
    descricao_c197: str
    descricao_e111: str | None
    # COD_OBS para o registro C195 (pai obrigatório do C197 na hierarquia SPED)
    # Tabela 5.3 — Observações de Lançamentos Fiscais (até 6 chars, específica do PA)
    obs_c195: str


CODIGOS: dict[str, CodigoAjuste] = {
    # ─── ICMS Antecipado Normal ────────────────────────────────────────────────
    # Base legal: Art. 107, Anexo I, RICMS-PA
    # Referência: Orientação 1146 - SEFA-PA
    # Regra: entrada SEM crédito; débito especial no E110; pagamento via DAR
    "NORMAL": CodigoAjuste(
        c197="PA70000010",
        e111=None,
        cod_receita_e116="1146",
        descricao_c197="ICMS ANTECIPADO - ART. 107, ANEXO I, RICMS-PA",
        descricao_e111=None,
        obs_c195="PA0010",
    ),

    # ─── ICMS Antecipado Especial ─────────────────────────────────────────────
    # Base legal: Art. 114-E, Anexo I, RICMS-PA
    # Referência: Orientação 1173 - SEFA-PA
    # Regra: entrada COM crédito (não encerra fase tributária);
    #        débito especial no E110; crédito via E111 (PA020008); pagamento via DARE
    "ESPECIAL": CodigoAjuste(
        c197="PA70000008",
        e111="PA020008",
        cod_receita_e116="1173",
        descricao_c197="ICMS ANTECIPADO ESPECIAL - ART. 114-E, ANEXO I, RICMS-PA",
        descricao_e111="OUTROS CREDITOS - ANTECIPACAO ESPECIAL - ART. 114-E, ANEXO I, RICMS-PA",
        obs_c195="PA0008",
    ),

    # ─── ICMS Antecipado Cesta Básica ─────────────────────────────────────────
    # Base legal: Art. 113, Anexo I, RICMS-PA
    # Referência: Orientação 1152 - SEFA-PA
    # Regra: entrada SEM crédito; débito especial no E110; pagamento via DAR
    "CESTA_BASICA": CodigoAjuste(
        c197="PA70000011",
        e111=None,
        cod_receita_e116="1152",
        descricao_c197="ICMS ANTECIPADO CESTA BASICA - ART. 113, ANEXO I, RICMS-PA",
        descricao_e111=None,
        obs_c195="PA0011",
    ),
}


def get_codigo(tipo_antecipacao: str) -> CodigoAjuste:
    """Retorna CodigoAjuste para o tipo dado. Lança ValueError se não encontrado."""
    try:
        return CODIGOS[tipo_antecipacao.upper()]
    except KeyError:
        validos = ", ".join(CODIGOS.keys())
        raise ValueError(f"Tipo de antecipação '{tipo_antecipacao}' inválido. Válidos: {validos}")
