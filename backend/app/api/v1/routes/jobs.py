"""Job endpoints: create, upload files, trigger processing, download output."""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.jobs import DownloadUrlResponse, JobCreate, JobRead
from app.core import storage
from app.core.config import settings
from app.core.deps import AnyAuthUser
from app.core.security import create_download_token, decode_token
from app.core.storage import StorageQuotaExceededError
from app.db.models import Company, JobLog, JobStatus, LogLevel, ProcessingJob, User
from app.db.session import get_db

router = APIRouter(tags=["jobs"])

_ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    "sped": {".txt"},
    "excel": {".xlsx", ".xls"},
}

# Bearer opcional — usado só em /output-file, que aceita token de download OU
# um Bearer normal (auto_error=False evita que o FastAPI exija o header antes
# de a rota poder checar o token de query primeiro).
_optional_bearer = HTTPBearer(auto_error=False)


async def _get_company_for_user(company_id: str, user, db: AsyncSession) -> Company:
    """Return company if it belongs to the user's accounting firm."""
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.accounting_firm_id == user.accounting_firm_id,
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")
    return company


async def _get_job_for_user(job_id: str, user, db: AsyncSession) -> ProcessingJob:
    result = await db.execute(
        select(ProcessingJob)
        .join(Company)
        .where(
            ProcessingJob.id == job_id,
            Company.accounting_firm_id == user.accounting_firm_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado")
    return job


# ─── Create Job ───────────────────────────────────────────────────────────────

@router.post(
    "/companies/{company_id}/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED
)
async def create_job(
    company_id: str,
    payload: JobCreate,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessingJob:
    await _get_company_for_user(company_id, current_user, db)

    job = ProcessingJob(
        company_id=company_id,
        created_by=current_user.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/companies/{company_id}/jobs", response_model=list[JobRead])
async def list_jobs(
    company_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[ProcessingJob]:
    await _get_company_for_user(company_id, current_user, db)
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.company_id == company_id)
        .offset(skip)
        .limit(limit)
        .order_by(ProcessingJob.created_at.desc())
    )
    return list(result.scalars().all())


# ─── Job Status / Detail ──────────────────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(
    job_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessingJob:
    return await _get_job_for_user(job_id, current_user, db)


# ─── File Uploads ─────────────────────────────────────────────────────────────

async def _upload_file(
    job: ProcessingJob,
    file: UploadFile,
    file_type: str,  # "sped" or "excel"
    db: AsyncSession,
) -> None:
    """Valida a extensão e grava o arquivo em disco (storage local — ver
    app/core/storage.py) em streaming, sem materializar tudo em memória."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS[file_type]:
        allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS[file_type]))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensão inválida para arquivo {file_type}. Permitido: {allowed}",
        )

    # Chave determinística (não usa o nome original) — evita arquivo órfão em
    # disco se o usuário reenviar com um nome diferente antes de processar.
    key = f"jobs/{job.id}/{file_type}_input{ext}"
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        total_bytes = await storage.save_upload(key, file, max_bytes)
    except StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Arquivo excede limite de {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    if file_type == "sped":
        job.sped_input_s3_key = key
    else:
        job.excel_input_s3_key = key

    db.add(JobLog(
        job_id=job.id,
        level=LogLevel.INFO,
        message=f"Arquivo {file_type} recebido: {file.filename} ({total_bytes // 1024} KB)",
    ))
    await db.commit()


@router.post("/jobs/{job_id}/upload/sped", status_code=status.HTTP_204_NO_CONTENT)
async def upload_sped(
    job_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
) -> None:
    job = await _get_job_for_user(job_id, current_user, db)
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Job não está em estado PENDING"
        )
    await _upload_file(job, file, "sped", db)


@router.post("/jobs/{job_id}/upload/excel", status_code=status.HTTP_204_NO_CONTENT)
async def upload_excel(
    job_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
) -> None:
    job = await _get_job_for_user(job_id, current_user, db)
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Job não está em estado PENDING"
        )
    await _upload_file(job, file, "excel", db)


# ─── Trigger Processing ───────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def trigger_processing(
    job_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    job = await _get_job_for_user(job_id, current_user, db)

    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Job não está em estado PENDING"
        )

    if not job.sped_input_s3_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo SPED não enviado"
        )

    if not job.excel_input_s3_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Planilha Excel não enviada"
        )

    # Transição atômica PENDING->PROCESSING: evita que 2 cliques rápidos (ou
    # 2 chamadas concorrentes) enfileirem 2 tasks para o mesmo job.
    result = await db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status == JobStatus.PENDING)
        .values(status=JobStatus.PROCESSING)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Job não está em estado PENDING"
        )

    from app.workers.tasks import process_sped_job
    process_sped_job.delay(job_id)

    return {"message": "Processamento iniciado", "job_id": job_id}


# ─── Download Output ──────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/download", response_model=DownloadUrlResponse)
async def download_output(
    job_id: str,
    request: Request,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DownloadUrlResponse:
    job = await _get_job_for_user(job_id, current_user, db)

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Job ainda não concluído"
        )

    if not job.sped_output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída não encontrado"
        )

    expires_in = settings.S3_PRESIGNED_URL_EXPIRE_SECONDS

    # Backend S3: URL pré-assinada direta do bucket, sem proxiar pela API.
    # Backend local: cai no fluxo de sempre (token curto + rota /output-file).
    presigned = await storage.get_presigned_url(job.sped_output_s3_key, expires_in)
    if presigned:
        return DownloadUrlResponse(url=presigned, expires_in_seconds=expires_in)

    token = create_download_token(job_id, expires_in)
    base_url = str(request.url_for("get_job_output_file", job_id=job_id))
    return DownloadUrlResponse(url=f"{base_url}?token={token}", expires_in_seconds=expires_in)


@router.get("/jobs/{job_id}/output-file", name="get_job_output_file")
async def get_job_output_file(
    job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str | None = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> FileResponse:
    """
    Serve o arquivo de saída do job. Aceita autenticação de duas formas:
    - `?token=...`: token de download de curta duração (gerado por
      /jobs/{id}/download) — usado pelo frontend via window.open, que não
      envia o header Authorization.
    - Bearer normal: para clientes de API.
    """
    job: ProcessingJob | None = None

    if token:
        try:
            payload = decode_token(token)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de download inválido ou expirado",
            )
        if payload.get("type") != "download" or payload.get("sub") != job_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de download inválido"
            )
        result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = result.scalar_one_or_none()
    elif credentials:
        try:
            payload = decode_token(credentials.credentials)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado"
            )
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
        result = await db.execute(select(User).where(User.id == payload.get("sub")))
        current_user = result.scalar_one_or_none()
        if not current_user or not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado ou inativo",
            )
        job = await _get_job_for_user(job_id, current_user, db)
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária"
        )

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado")

    if not job.sped_output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída não encontrado"
        )

    file_path = storage.local_path_for(job.sped_output_s3_key)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo de saída não encontrado em disco",
        )

    return FileResponse(
        file_path,
        media_type="text/plain",
        filename=f"sped_enriquecido_{job_id[:8]}.txt",
    )


# ─── Job Logs ─────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: str,
    current_user: AnyAuthUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    await _get_job_for_user(job_id, current_user, db)
    result = await db.execute(
        select(JobLog)
        .where(JobLog.job_id == job_id)
        .order_by(JobLog.created_at)
    )
    logs = result.scalars().all()
    return [
        {"level": log.level.value, "message": log.message, "created_at": log.created_at.isoformat()}
        for log in logs
    ]
