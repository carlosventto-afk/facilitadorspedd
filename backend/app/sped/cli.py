"""
CLI para processamento local do SPED EFD ICMS/IPI.

Uso:
    python -m app.sped.cli process \
        --sped input.txt \
        --excel antecipacoes.xlsx \
        --out saida.txt

O arquivo de saída é validado pelo Validador SPED da SEFAZ antes da entrega.
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s  %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _cmd_process(args: argparse.Namespace) -> int:
    from app.excel.sefa_parser import parse_sefa_excel
    from app.sped.matcher import match_anticipations
    from app.sped.parser import SpedParser
    from app.sped.writer import SpedEnricher

    sped_path = Path(args.sped)
    excel_path = Path(args.excel)
    out_path = Path(args.out)

    if not sped_path.exists():
        print(f"ERRO: Arquivo SPED não encontrado: {sped_path}", file=sys.stderr)
        return 1
    if not excel_path.exists():
        print(f"ERRO: Planilha não encontrada: {excel_path}", file=sys.stderr)
        return 1

    print(f"[1/4] Indexando arquivo SPED: {sped_path.name} ...")
    parser = SpedParser()
    try:
        index = parser.parse(sped_path)
    except Exception as exc:
        print(f"ERRO ao indexar SPED: {exc}", file=sys.stderr)
        return 1

    print(
        f"      {len(index.c100_blocks)} notas fiscais encontradas | "
        f"E110 na linha {index.e110_line}"
    )

    print(f"[2/4] Lendo planilha SEFA-PA: {excel_path.name} ...")
    try:
        anticipations = parse_sefa_excel(excel_path)
    except Exception as exc:
        print(f"ERRO ao ler planilha: {exc}", file=sys.stderr)
        return 1

    print(f"      {len(anticipations)} antecipações carregadas")

    print("[3/4] Associando antecipações às notas fiscais ...")
    matched, unmatched = match_anticipations(index, anticipations)

    if unmatched:
        print(f"\n  AVISO: {len(unmatched)} antecipação(ões) sem correspondência no SPED:")
        for ant in unmatched:
            print(f"    NF {ant.numero_nf} série {ant.serie} CNPJ {ant.emitente_cnpj} tipo {ant.tipo}")
        print()

    print(f"      {len(matched)} correspondências | {len(unmatched)} sem match")

    if not matched:
        print("\nNenhuma antecipação foi associada. Verifique a planilha e o arquivo SPED.")
        return 2

    print(f"[4/4] Enriquecendo SPED -> {out_path.name} ...")
    enricher = SpedEnricher()
    try:
        result = enricher.enrich(sped_path, out_path, index, matched)
    except Exception as exc:
        print(f"ERRO ao enriquecer SPED: {exc}", file=sys.stderr)
        return 1

    print("\n-- Resultado ------------------------------------------")
    print(f"  C197 inseridos   : {result.c197_inserted}")
    print(f"  E111 inseridos   : {result.e111_inserted}")
    print(f"  E116 inseridos   : {result.e116_inserted}")
    print(f"  Notas encontradas: {result.nfs_found}")
    print(f"  Antecipações     : {result.anticipations_matched}/{result.anticipations_total} com match")
    print(f"  Total ICMS       : R$ {result.total_icms_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    print(f"\n  Arquivo gerado   : {out_path.resolve()}")
    print("\nValidar o arquivo no Validador SPED oficial antes de assinar e transmitir.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.sped.cli",
        description="FacilitadorSped — Motor de processamento SPED EFD ICMS/IPI",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Saída detalhada")
    subparsers = parser.add_subparsers(dest="command")

    process_parser = subparsers.add_parser(
        "process", help="Processa um arquivo SPED inserindo os registros de antecipação"
    )
    process_parser.add_argument("--sped", required=True, metavar="FILE", help="Arquivo SPED de entrada (.txt)")
    process_parser.add_argument("--excel", required=True, metavar="FILE", help="Planilha SEFA-PA (.xlsx)")
    process_parser.add_argument("--out", required=True, metavar="FILE", help="Arquivo SPED de saída (.txt)")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "process":
        sys.exit(_cmd_process(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
