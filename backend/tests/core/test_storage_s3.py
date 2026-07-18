"""Testes do backend S3 de app/core/storage.py — via moto, sem AWS real.

O backend local já é exercitado indiretamente pelos testes de tests/api/
(upload/download reais através da API). Este arquivo cobre especificamente
o backend S3 (ensure_local/publish_local/save_upload/get_presigned_url/
delete), que fica inativo por padrão e só é ativado com credenciais reais.
"""
from __future__ import annotations

import io
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi import UploadFile
from moto import mock_aws

from app.core import storage
from app.core.config import settings

BUCKET = "facilitador-sped-test"


@pytest.fixture(autouse=True)
def _s3_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Liga o backend S3 (credenciais falsas, aceitas pelo moto) e isola a
    área de staging local num diretório de teste."""
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(settings, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", tmp_path / "staging")


@pytest.fixture
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _upload_file(content: bytes, filename: str = "arquivo.txt") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


def test_s3_enabled_apenas_com_credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    assert storage._s3_enabled() is False
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "testing")
    assert storage._s3_enabled() is True


async def test_save_upload_sobe_pro_s3(s3_bucket) -> None:
    content = b"conteudo de teste do SPED"
    total = await storage.save_upload(
        "jobs/1/sped_input.txt", _upload_file(content), max_bytes=1_000_000
    )
    assert total == len(content)

    obj = s3_bucket.get_object(Bucket=BUCKET, Key="jobs/1/sped_input.txt")
    assert obj["Body"].read() == content


async def test_save_upload_nao_deixa_copia_local_depois_de_subir(s3_bucket) -> None:
    key = "jobs/1/sped_input.txt"
    await storage.save_upload(key, _upload_file(b"conteudo"), max_bytes=1_000_000)
    assert not storage.local_path_for(key).exists()


async def test_save_upload_ainda_respeita_limite_de_tamanho(s3_bucket) -> None:
    with pytest.raises(storage.StorageQuotaExceededError):
        await storage.save_upload("jobs/1/grande.txt", _upload_file(b"x" * 100), max_bytes=10)


async def test_ensure_local_baixa_do_s3(s3_bucket) -> None:
    key = "jobs/1/sped_input.txt"
    content = b"conteudo do sped"
    s3_bucket.put_object(Bucket=BUCKET, Key=key, Body=content)

    path = await storage.ensure_local(key)
    assert path.exists()
    assert path.read_bytes() == content


async def test_ensure_local_nao_baixa_de_novo_se_ja_tem_copia_local(s3_bucket) -> None:
    key = "jobs/1/sped_input.txt"
    s3_bucket.put_object(Bucket=BUCKET, Key=key, Body=b"original")

    path = await storage.ensure_local(key)
    path.write_bytes(b"modificado localmente")  # simula reuso dentro da mesma task

    path2 = await storage.ensure_local(key)
    assert path2.read_bytes() == b"modificado localmente"  # não baixou de novo


async def test_ensure_local_chave_inexistente_levanta_erro(s3_bucket) -> None:
    with pytest.raises(ClientError):
        await storage.ensure_local("jobs/inexistente/sped_input.txt")


async def test_publish_local_sobe_e_limpa_staging(s3_bucket) -> None:
    key = "jobs/1/sped_output.txt"
    path = storage.local_path_for(key, ensure_parent=True)
    path.write_bytes(b"sped enriquecido")

    await storage.publish_local(key)

    assert not path.exists()
    obj = s3_bucket.get_object(Bucket=BUCKET, Key=key)
    assert obj["Body"].read() == b"sped enriquecido"


async def test_publish_local_e_no_op_sem_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    key = "jobs/1/sped_output.txt"
    path = storage.local_path_for(key, ensure_parent=True)
    path.write_bytes(b"sped enriquecido")

    await storage.publish_local(key)

    assert path.exists()  # continua lá — backend local não sobe nem apaga


async def test_get_presigned_url_retorna_none_sem_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    url = await storage.get_presigned_url("jobs/1/sped_output.txt", 900)
    assert url is None


async def test_get_presigned_url_retorna_url_com_s3(s3_bucket) -> None:
    key = "jobs/1/sped_output.txt"
    s3_bucket.put_object(Bucket=BUCKET, Key=key, Body=b"dados")

    url = await storage.get_presigned_url(key, 900)
    assert url is not None
    assert BUCKET in url


async def test_delete_remove_do_s3(s3_bucket) -> None:
    key = "jobs/1/sped_output.txt"
    s3_bucket.put_object(Bucket=BUCKET, Key=key, Body=b"dados")

    await storage.delete(key)

    with pytest.raises(ClientError):
        s3_bucket.get_object(Bucket=BUCKET, Key=key)
