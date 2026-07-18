"""
Armazenamento de arquivos de job (SPED de entrada/saída, planilha Excel).

Dois backends, escolhidos automaticamente por config — sem precisar mudar
nenhum código quando ligar um ou outro:

- **Local** (padrão em dev, quando AWS_ACCESS_KEY_ID não está configurada):
  disco compartilhado entre `backend` e `celery_worker` via bind mount/volume
  no docker-compose.yml. Só funciona se os dois processos compartilharem o
  mesmo filesystem.
- **S3** (ativado assim que AWS_ACCESS_KEY_ID estiver configurada): funciona
  com `backend`/`celery_worker` como serviços totalmente separados sem
  volume compartilhado (ex. Railway, ECS) — o cenário de deploy real.

As colunas do banco continuam nomeadas `*_s3_key` nos dois casos — é sempre
uma string relativa (ex. "jobs/{job_id}/sped_input.txt").

O motor SPED (app/sped/) sempre lê/escreve um Path local de verdade (streaming
de arquivos de até 24MB+/271k linhas, não caberia bem em memória nem faria
sentido operar direto sobre uma API remota) — nunca opera direto sobre S3.
`local_path_for` é usado como área de staging em disco pros dois backends:
no backend local É o destino final; no backend S3 é só uma cópia de trabalho
temporária, sincronizada via `ensure_local`/`publish_local`.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1MB


class StorageQuotaExceededError(Exception):
    """Levantado quando um upload excede o tamanho máximo permitido."""


def _s3_enabled() -> bool:
    return bool(settings.AWS_ACCESS_KEY_ID and settings.S3_BUCKET)


def _s3_client() -> Any:
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


def _base_dir() -> Path:
    return Path(settings.LOCAL_STORAGE_DIR)


def local_path_for(key: str, *, ensure_parent: bool = False) -> Path:
    """
    Resolve uma chave de storage para um Path real em disco — destino final
    no backend local, área de staging temporária no backend S3.

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
    Grava um UploadFile em streaming (por chunks), sem materializar o
    arquivo inteiro em memória. Aborta e remove o arquivo parcial se o
    total gravado exceder `max_bytes`. No backend S3, sobe o arquivo depois
    de gravado localmente (streaming direto pro S3 exigiria multipart upload
    incremental — não vale a complexidade para os tamanhos de arquivo desta
    aplicação, poucas dezenas de MB).

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

    if _s3_enabled():
        await publish_local(key)

    return total


async def ensure_local(key: str) -> Path:
    """
    Garante que o arquivo da chave está disponível em `local_path_for(key)`
    e devolve esse Path — o motor SPED sempre lê de um Path local de
    verdade, nunca de S3 diretamente.

    Backend local: o arquivo já está lá (levantado FileNotFoundError se não
    estiver). Backend S3: baixa do bucket (a menos que já exista uma cópia
    local, ex. nova tentativa da mesma task).
    """
    path = local_path_for(key, ensure_parent=True)
    if _s3_enabled():
        if not path.exists():
            await asyncio.to_thread(_s3_client().download_file, settings.S3_BUCKET, key, str(path))
    elif not path.exists():
        raise FileNotFoundError(key)
    return path


async def publish_local(key: str) -> None:
    """
    Publica o arquivo já escrito em `local_path_for(key)` no backend real.

    Backend local: no-op (já é o destino final). Backend S3: sobe o arquivo
    e remove a cópia local de staging (não precisa mais dela, e evita que o
    disco do container cresça sem limite ao longo de vários jobs).
    """
    if not _s3_enabled():
        return
    path = local_path_for(key)
    await asyncio.to_thread(_s3_client().upload_file, str(path), settings.S3_BUCKET, key)
    path.unlink(missing_ok=True)


async def get_presigned_url(key: str, expires_in_seconds: int) -> str | None:
    """
    URL pré-assinada direta do S3 para download — só faz sentido no backend
    S3 (evita proxiar o arquivo pela API). Backend local retorna None; quem
    chamou deve usar o fluxo existente de token curto + rota /output-file.
    """
    if not _s3_enabled():
        return None
    return await asyncio.to_thread(
        _s3_client().generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires_in_seconds,
    )


async def delete(key: str) -> None:
    local_path_for(key).unlink(missing_ok=True)
    if _s3_enabled():
        await asyncio.to_thread(_s3_client().delete_object, Bucket=settings.S3_BUCKET, Key=key)
