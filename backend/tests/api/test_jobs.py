"""Testes de API do fluxo de jobs: criar, upload, processar, baixar."""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import Company, User
from tests._helpers import write_minimal_sefa_excel, write_minimal_sped

from .conftest import auth_headers

S3_BUCKET = "facilitador-sped-test"

CHAVE_A = "35260304165376000107550010001554691944403164"
CHAVE_B = "35260304165376000107550010009999991944403164"
CHAVE_C = "35260304165376000107550010008888881944403164"


async def _create_job(client: AsyncClient, company: Company, headers: dict) -> str:
    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _upload_pair(
    client: AsyncClient, job_id: str, headers: dict, tmp_path: Path,
    company: Company, chave: str, icms: float = 500.00,
) -> None:
    sped_path = write_minimal_sped(
        tmp_path, chave_nfe=chave, cnpj=company.cnpj, filename=f"{chave}.txt"
    )
    with sped_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/sped",
            files={"file": ("sped.txt", f, "text/plain")},
            headers=headers,
        )
    assert r.status_code == 204, r.text

    excel_path = write_minimal_sefa_excel(
        tmp_path, chave_nfe=chave, cnpj=company.cnpj, icms_a_pagar=icms, filename=f"{chave}.xlsx"
    )
    with excel_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/excel",
            files={
                "file": (
                    "sefa.xlsx",
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            headers=headers,
        )
    assert r.status_code == 204, r.text


# ── Fluxo feliz ────────────────────────────────────────────────────────────────

async def test_fluxo_completo_upload_processar_download(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)
    await _upload_pair(client, job_id, headers, tmp_path, company, CHAVE_A, icms=500.00)

    # processa direto (sem Celery/broker) — mesmo padrão que o worker usaria
    result = await run_sped_processing(job_id, session_factory=session_factory)
    assert result["status"] == "completed"

    r = await client.get(f"/jobs/{job_id}", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "COMPLETED"
    assert data["nfs_found"] == 1
    assert data["anticipations_matched"] == 1
    assert data["anticipations_total"] == 1
    assert data["c197_records_inserted"] == 1
    assert data["e111_records_inserted"] == 1
    assert data["e116_records_inserted"] == 1

    r = await client.get(f"/jobs/{job_id}/download", headers=headers)
    assert r.status_code == 200
    download_url = r.json()["url"]
    assert download_url.startswith("http")  # URL absoluta, não relativa (bug corrigido)

    r = await client.get(download_url)  # sem headers — autenticação vem do token na query
    assert r.status_code == 200
    assert b"|E116|" in r.content
    assert r.headers["content-disposition"].startswith("attachment")


async def test_fluxo_completo_com_backend_s3(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mesmo fluxo de ponta a ponta do teste acima, mas com o backend S3
    ligado (via moto — sem AWS real): upload sobe pro S3, a task baixa pra
    processar e publica o resultado de volta no S3, e o link de download
    devolvido é uma URL pré-assinada do S3, não a rota /output-file local."""
    from app.workers.tasks import run_sped_processing

    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(settings, "S3_BUCKET", S3_BUCKET)

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=S3_BUCKET)

        headers = auth_headers(gestor_user)
        job_id = await _create_job(client, company, headers)
        await _upload_pair(client, job_id, headers, tmp_path, company, CHAVE_A, icms=500.00)

        # upload já deve ter ido pro S3, não pro disco local
        r = await client.get(f"/jobs/{job_id}", headers=headers)
        sped_key = f"jobs/{job_id}/sped_input.txt"
        s3.head_object(Bucket=S3_BUCKET, Key=sped_key)  # não levanta = existe

        result = await run_sped_processing(job_id, session_factory=session_factory)
        assert result["status"] == "completed"

        r = await client.get(f"/jobs/{job_id}/download", headers=headers)
        assert r.status_code == 200
        download_url = r.json()["url"]
        assert S3_BUCKET in download_url
        assert "/output-file" not in download_url  # URL pré-assinada direta, não a rota local

        output_key = f"jobs/{job_id}/sped_output.txt"
        obj = s3.get_object(Bucket=S3_BUCKET, Key=output_key)
        assert b"|E116|" in obj["Body"].read()


async def test_anticipations_total_conta_tambem_os_sem_match(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    """Regressão do bug de contrato: ProcessingResult.anticipations_total do
    motor é sempre igual a anticipations_matched (o motor não recebe a lista
    de não-casados) — a task precisa somar matched+unmatched ela mesma."""
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)

    sped_path = write_minimal_sped(tmp_path, chave_nfe=CHAVE_A, cnpj=company.cnpj)
    with sped_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/sped",
            files={"file": ("sped.txt", f, "text/plain")},
            headers=headers,
        )
    assert r.status_code == 204

    # Excel referencia uma chave E um número de NF que não existem no SPED
    # (chave errada sozinha não bastaria: o matcher cai pro fallback por
    # CNPJ+NF+série, que casaria mesmo assim já que usam o mesmo default) ->
    # fica genuinamente "unmatched"
    excel_path = write_minimal_sefa_excel(
        tmp_path,
        chave_nfe="00000000000000000000000000000000000000000000",
        cnpj=company.cnpj,
        serie_nota="1/9999999",
    )
    with excel_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/excel",
            files={"file": ("sefa.xlsx", f, "application/octet-stream")},
            headers=headers,
        )
    assert r.status_code == 204

    result = await run_sped_processing(job_id, session_factory=session_factory)
    assert result["status"] == "failed"  # nada casou -> SpedProcessingError

    r = await client.get(f"/jobs/{job_id}", headers=headers)
    data = r.json()
    assert data["status"] == "FAILED"
    assert data["anticipations_total"] is None  # falhou antes de calcular estatísticas
    assert data["error_message"]


# ── Wiring do endpoint /process com Celery ─────────────────────────────────────

async def test_process_endpoint_transicao_atomica_e_conclui(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirma que POST /process muda o status pra PROCESSING de forma
    atômica ANTES de disparar a task (fecha a corrida de disparo duplo), e
    que a task disparada (simulada aqui, sem broker real) processa com
    sucesso. Não usa celery task_always_eager: a task real faz
    asyncio.run(...) internamente, o que quebra dentro do loop já rodando
    do teste — por isso o .delay() é monkeypatchado para só registrar a
    chamada, e o processamento em si é exercitado chamando
    run_sped_processing diretamente, como o worker faria."""
    from app.workers import tasks

    dispatched: list[str] = []
    monkeypatch.setattr(tasks.process_sped_job, "delay", lambda job_id: dispatched.append(job_id))

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)
    await _upload_pair(client, job_id, headers, tmp_path, company, CHAVE_B)

    r = await client.post(f"/jobs/{job_id}/process", headers=headers)
    assert r.status_code == 202
    assert dispatched == [job_id]

    # a rota já deve ter marcado PROCESSING antes mesmo do "worker" rodar
    r = await client.get(f"/jobs/{job_id}", headers=headers)
    assert r.json()["status"] == "PROCESSING"

    result = await tasks.run_sped_processing(job_id, session_factory=session_factory)
    assert result["status"] == "completed"

    r = await client.get(f"/jobs/{job_id}", headers=headers)
    assert r.json()["status"] == "COMPLETED"


async def test_dois_disparos_seguidos_o_segundo_falha(
    client: AsyncClient,
    gestor_user: User,
    company: Company,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão da corrida de disparo duplo: a transição PENDING->PROCESSING
    é atômica (UPDATE ... WHERE status='PENDING'), então o 2º POST /process
    pro mesmo job (já não mais PENDING) deve ser rejeitado."""
    from app.workers import tasks

    monkeypatch.setattr(tasks.process_sped_job, "delay", lambda job_id: None)

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)
    await _upload_pair(client, job_id, headers, tmp_path, company, CHAVE_C)

    r1 = await client.post(f"/jobs/{job_id}/process", headers=headers)
    r2 = await client.post(f"/jobs/{job_id}/process", headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 400


# ── Erros ────────────────────────────────────────────────────────────────────

async def test_process_sem_upload_retorna_400(
    client: AsyncClient, gestor_user: User, company: Company,
) -> None:
    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)
    r = await client.post(f"/jobs/{job_id}/process", headers=headers)
    assert r.status_code == 400


async def test_upload_extensao_invalida_retorna_400(
    client: AsyncClient, gestor_user: User, company: Company, tmp_path: Path,
) -> None:
    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)

    bad_file = tmp_path / "documento.pdf"
    bad_file.write_bytes(b"nao e um sped")
    with bad_file.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/sped",
            files={"file": ("documento.pdf", f, "application/pdf")},
            headers=headers,
        )
    assert r.status_code == 400


async def test_upload_excede_tamanho_retorna_413(
    client: AsyncClient, gestor_user: User, company: Company, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)  # qualquer byte já estoura

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)

    sped_path = write_minimal_sped(tmp_path, chave_nfe=CHAVE_A, cnpj=company.cnpj)
    with sped_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/sped",
            files={"file": ("sped.txt", f, "text/plain")},
            headers=headers,
        )
    assert r.status_code == 413


async def test_sped_malformado_falha_sem_retry(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)
    job_id = await _create_job(client, company, headers)

    sped_malformado = tmp_path / "sped_ruim.txt"
    sped_malformado.write_text("isto nao e um SPED valido\n", encoding="latin-1")
    with sped_malformado.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/sped",
            files={"file": ("sped.txt", f, "text/plain")},
            headers=headers,
        )
    assert r.status_code == 204

    excel_path = write_minimal_sefa_excel(tmp_path, chave_nfe=CHAVE_A, cnpj=company.cnpj)
    with excel_path.open("rb") as f:
        r = await client.post(
            f"/jobs/{job_id}/upload/excel",
            files={"file": ("sefa.xlsx", f, "application/octet-stream")},
            headers=headers,
        )
    assert r.status_code == 204

    # run_sped_processing NÃO deve levantar SpedProcessingError — ela é
    # capturada internamente e vira status FAILED (sem acionar retry Celery).
    result = await run_sped_processing(job_id, session_factory=session_factory)
    assert result["status"] == "failed"

    r = await client.get(f"/jobs/{job_id}", headers=headers)
    data = r.json()
    assert data["status"] == "FAILED"
    assert data["error_message"]
