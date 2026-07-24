"""Testes de API do fluxo de jobs: criar, upload, processar, baixar."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    AccountingFirm,
    Company,
    CreditStatus,
    OperatorCompanyLink,
    PendingAntecipacaoCredit,
    User,
    UserRole,
)
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
    titulo: str = "Receita: 1173 - Antecipado Especial",
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
        tmp_path, chave_nfe=chave, cnpj=company.cnpj, icms_a_pagar=icms,
        titulo=titulo, filename=f"{chave}.xlsx",
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
    # NÃO 1: orientação SEFA-PA 1173 §2 — o crédito ESPECIAL só pode ser
    # apropriado (E111) no mês SEGUINTE ao débito, nunca no mesmo job. Este é
    # o primeiro job da empresa, então os 500,00 viram crédito PENDENTE (ver
    # test_credito_especial_e111_reivindicado_no_periodo_seguinte abaixo),
    # não um E111 lançado agora.
    assert data["e111_records_inserted"] == 0
    assert data["e116_records_inserted"] == 1

    r = await client.get(f"/jobs/{job_id}/download", headers=headers)
    assert r.status_code == 200
    download_url = r.json()["url"]
    assert download_url.startswith("http")  # URL absoluta, não relativa (bug corrigido)

    r = await client.get(download_url)  # sem headers — autenticação vem do token na query
    assert r.status_code == 200
    assert b"|E116|" in r.content
    assert r.headers["content-disposition"].startswith("attachment")


# ── Crédito ESPECIAL pendente (SEFA-PA 1173 §2) ──────────────────────────────

async def test_credito_especial_e111_reivindicado_no_periodo_seguinte(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    """Ciclo completo: job de Junho gera débito ESPECIAL (E111=0, vira crédito
    PENDENTE); job de Julho da MESMA empresa reivindica esse crédito (E111=1,
    com o valor de Junho) mesmo sem ESPECIAL nenhum no próprio match de Julho
    — prova que o E111 vem do crédito pendente, não do período atual."""
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)

    # Junho: ESPECIAL 500,00 → débito lançado, crédito fica pendente
    # (_create_job usa period 2026-06-01/2026-06-30)
    job1_id = await _create_job(client, company, headers)
    await _upload_pair(client, job1_id, headers, tmp_path, company, CHAVE_A, icms=500.00)
    result1 = await run_sped_processing(job1_id, session_factory=session_factory)
    assert result1["status"] == "completed"

    async with session_factory() as db:
        credits = (await db.execute(select(PendingAntecipacaoCredit))).scalars().all()
        assert len(credits) == 1
        assert credits[0].valor == Decimal("500.00")
        assert credits[0].status == CreditStatus.PENDING
        assert credits[0].company_id == company.id

    # Julho: sem ESPECIAL no match desta vez (só NORMAL) — mas deve
    # reivindicar o crédito pendente de Junho mesmo assim
    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-07-01", "period_end": "2026-07-31"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    job2_id = r.json()["id"]
    await _upload_pair(
        client, job2_id, headers, tmp_path, company, CHAVE_B, icms=100.00,
        titulo="Receita: 1146 - Antecipado Normal",
    )
    result2 = await run_sped_processing(job2_id, session_factory=session_factory)
    assert result2["status"] == "completed"

    r = await client.get(f"/jobs/{job2_id}", headers=headers)
    data = r.json()
    assert data["e111_records_inserted"] == 1

    r = await client.get(f"/jobs/{job2_id}/download", headers=headers)
    download_url = r.json()["url"]
    r = await client.get(download_url)
    assert b"|E111|PA020008|" in r.content
    assert b"500,00" in r.content   # crédito de Junho, não algo derivado de Julho

    async with session_factory() as db:
        credit = (await db.execute(select(PendingAntecipacaoCredit))).scalar_one()
        assert credit.status == CreditStatus.CLAIMED
        assert credit.claimed_in_job_id == job2_id


async def test_credito_especial_mes_pulado_ainda_e_reivindicado(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    """Se a empresa pular um mês (processar Janeiro, depois só Março, sem
    Fevereiro), o crédito de Janeiro ainda deve ser reivindicado em Março —
    não expira por causa do mês pulado (ver conversa registrada na memória
    do projeto: resposta simulada, não confirmada por contador real)."""
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)

    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        headers=headers,
    )
    job1_id = r.json()["id"]
    await _upload_pair(client, job1_id, headers, tmp_path, company, CHAVE_A, icms=300.00)
    await run_sped_processing(job1_id, session_factory=session_factory)

    # Fevereiro nunca é processado — pula direto pra Março
    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
        headers=headers,
    )
    job2_id = r.json()["id"]
    await _upload_pair(
        client, job2_id, headers, tmp_path, company, CHAVE_B, icms=50.00,
        titulo="Receita: 1146 - Antecipado Normal",
    )
    result2 = await run_sped_processing(job2_id, session_factory=session_factory)
    assert result2["status"] == "completed"

    r = await client.get(f"/jobs/{job2_id}", headers=headers)
    assert r.json()["e111_records_inserted"] == 1

    async with session_factory() as db:
        credit = (await db.execute(select(PendingAntecipacaoCredit))).scalar_one()
        assert credit.status == CreditStatus.CLAIMED
        assert credit.valor == Decimal("300.00")


async def test_reprocessamento_apos_credito_reivindicado_nao_sobrescreve(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    gestor_user: User,
    company: Company,
    tmp_path: Path,
) -> None:
    """Se o job de origem do crédito for reprocessado DEPOIS do crédito já
    ter sido reivindicado num período seguinte, e o valor recalculado for
    diferente do original, o registro já reivindicado NÃO deve ser
    sobrescrito silenciosamente (o EFD que já usou esse valor pode já ter
    sido transmitido à SEFA) — só um JobLog de aviso para revisão manual."""
    from app.core import storage
    from app.db.models import JobLog, LogLevel
    from app.workers.tasks import run_sped_processing

    headers = auth_headers(gestor_user)

    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        headers=headers,
    )
    job1_id = r.json()["id"]
    await _upload_pair(client, job1_id, headers, tmp_path, company, CHAVE_A, icms=100.00)
    await run_sped_processing(job1_id, session_factory=session_factory)

    r = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-02-01", "period_end": "2026-02-28"},
        headers=headers,
    )
    job2_id = r.json()["id"]
    await _upload_pair(
        client, job2_id, headers, tmp_path, company, CHAVE_B, icms=10.00,
        titulo="Receita: 1146 - Antecipado Normal",
    )
    await run_sped_processing(job2_id, session_factory=session_factory)

    async with session_factory() as db:
        credit = (await db.execute(select(PendingAntecipacaoCredit))).scalar_one()
        assert credit.status == CreditStatus.CLAIMED
        assert credit.valor == Decimal("100.00")

    # Sobrescreve o Excel de origem do job1 com um valor DIFERENTE (simula
    # dado de entrada corrigido) e reprocessa o MESMO job_id diretamente —
    # é assim que um retry automático do Celery reprocessaria.
    async with session_factory() as db:
        from app.db.models import ProcessingJob
        job1 = (
            await db.execute(select(ProcessingJob).where(ProcessingJob.id == job1_id))
        ).scalar_one()
        excel_key = job1.excel_input_s3_key

    excel_path = storage.local_path_for(excel_key)
    new_excel = write_minimal_sefa_excel(
        tmp_path, chave_nfe=CHAVE_A, cnpj=company.cnpj, icms_a_pagar=999.00,
        filename="reprocessed.xlsx",
    )
    excel_path.write_bytes(new_excel.read_bytes())

    result1_retry = await run_sped_processing(job1_id, session_factory=session_factory)
    assert result1_retry["status"] == "completed"

    async with session_factory() as db:
        credit = (await db.execute(select(PendingAntecipacaoCredit))).scalar_one()
        # Continua com o valor original reivindicado — NÃO foi sobrescrito
        assert credit.valor == Decimal("100.00")
        assert credit.status == CreditStatus.CLAIMED

        warn_logs = (
            await db.execute(
                select(JobLog).where(JobLog.job_id == job1_id, JobLog.level == LogLevel.WARN)
            )
        ).scalars().all()
        assert len(warn_logs) == 1
        assert "divergência" in warn_logs[0].message.lower()


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


# ── Isolamento de Operador por vínculo de empresa ───────────────────────────

async def test_operador_cria_job_so_para_empresa_vinculada(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm, company: Company,
) -> None:
    operador = User(
        email="operador.jobs@teste.com.br",
        password_hash=hash_password("Senha@123"),
        full_name="Operador Teste",
        role=UserRole.OPERADOR,
        accounting_firm_id=accounting_firm.id,
    )
    db.add(operador)
    empresa_nao_vinculada = Company(
        accounting_firm_id=accounting_firm.id, name="Não Vinculada", cnpj="66554433000111",
        uf="PA",
    )
    db.add(empresa_nao_vinculada)
    await db.commit()
    await db.refresh(operador)
    await db.refresh(empresa_nao_vinculada)

    db.add(OperatorCompanyLink(user_id=operador.id, company_id=company.id))
    await db.commit()

    headers = auth_headers(operador)

    r_ok = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
        headers=headers,
    )
    assert r_ok.status_code == 201, r_ok.text

    r_bloqueado = await client.post(
        f"/companies/{empresa_nao_vinculada.id}/jobs",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
        headers=headers,
    )
    assert r_bloqueado.status_code == 404


async def test_gestor_continua_sem_precisar_de_vinculo(
    client: AsyncClient, company: Company, gestor_user: User,
) -> None:
    """Regressão: a restrição por vínculo é só pra OPERADOR — GESTOR continua
    acessando qualquer empresa do escritório sem nenhum vínculo explícito
    (comportamento idêntico ao de antes desta mudança)."""
    r_gestor = await client.post(
        f"/companies/{company.id}/jobs",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
        headers=auth_headers(gestor_user),
    )
    assert r_gestor.status_code == 201, r_gestor.text
