"""
Armazenamento de arquivos de job (SPED de entrada/saída, planilha Excel).

Implementação atual: disco local, compartilhado entre os containers `backend`
e `celery_worker` via bind mount/volume no docker-compose.yml. As colunas do
banco continuam nomeadas `*_s3_key` de propósito — a chave aqui é só uma
string relativa (ex. "jobs/{job_id}/sped_input.txt"), então trocar por S3
mais adiante é questão de reescrever o interior destas funções, sem mudar
quem as chama nem o schema do banco.

LIMITAÇÃO CONHECIDA: isto só funciona se os processos que gravam e os que
leem compartilharem o mesmo filesystem (verdade hoje em dev via
docker-compose, NÃO garantido se `backend`/`celery_worker` forem deployados
como serviços separados sem volume compartilhado, ex. Railway). Migrar para
S3 antes de qualquer deploy multi-serviço.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

_CHUNK_SIZE = 1024 * 1024  # 1MB


class StorageQuotaExceededError(Exception):
    """Levantado quando um upload excede o tamanho máximo permitido."""


def _base_dir() -> Path:
    return Path(settings.LOCAL_STORAGE_DIR)


def local_path_for(key: str, *, ensure_parent: bool = False) -> Path:
    """
    Resolve uma chave de storage para um Path real em disco.

    Sanitiza contra path traversal (ex. "../../etc/passwd") garantindo que o
    resultado final continue dentro do diretório base.
    """
    base = _base_dir().resolve()
    candidate = (base / key).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Chave de storage inválida (fora do diretório base): {key!r}")

    if ensure_parent:
        candidate.parent.mkdir(parents=True, exist_ok=True)

    return candidate


async def save_upload(key: str, file: UploadFile, max_bytes: int) -> int:
    """
    Grava um UploadFile em disco em streaming (por chunks), sem materializar
    o arquivo inteiro em memória. Aborta e remove o arquivo parcial se o
    total gravado exceder `max_bytes`.

    Retorna o número total de bytes gravados.
    """
    dest = local_path_for(key, ensure_parent=True)
    total = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise StorageQuotaExceededError(
                        f"Arquivo excede o limite de {max_bytes} bytes"
                    )
                out.write(chunk)
    except StorageQuotaExceededError:
        dest.unlink(missing_ok=True)
        raise
    return total


def delete(key: str) -> None:
    local_path_for(key).unlink(missing_ok=True)
