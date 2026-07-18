"""Celery tasks for SPED processing jobs."""
import logging
from datetime import UTC, date, datetime

from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class SpedProcessingError(Exception):
    """Erro de negócio (arquivo malformado, planilha inválida, etc.) — marca
    o job como FAILED sem acionar retry do Celery, já que reprocessar o
    mesmo arquivo nunca vai ter sucesso sozinho."""


class ProcessingTask(Task):
    """Base task with DB session handling."""
    abstract = True


def _parse_ddmmaaaa(value: str | None) -> date | None:
    """Converte data DDMMAAAA (formato usado pelo motor SPED) para date."""
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%d%m%Y").date()
    except ValueError:
        return None


async def run_sped_processing(
    job_id: str,
    session_factory: async_sessionmaker | None = None,
) -> dict:
    """
    Lógica real de processamento, extraída da task Celery para poder ser
    chamada diretamente (com um session_factory de teste injetado) sem
    precisar de um worker/broker Celery real.

    Quando session_factory não é passado (caminho real do Celery), cria um
    engine novo, escopado a esta chamada, e descarta no final. O engine NÃO
    pode ser cacheado em variável de módulo aqui: process_sped_job chama
    asyncio.run() a cada execução, o que cria um event loop novo por task, e
    um engine assíncrono (com pool de conexões asyncpg) criado num loop não
    pode ser reutilizado depois que aquele loop fecha — a 2ª task do mesmo
    worker quebrava com "got Future ... attached to a different loop".
    """
    from sqlalchemy import select

    from app.core import storage
    from app.db.models import (
        AnticipationRecord,
        JobLog,
        JobStatus,
        LogLevel,
        ProcessingJob,
        TipoAntecipacao,
    )

    engine = None
    if session_factory is None:
        from app.core.config import settings
        engine = create_async_engine(settings.DATABASE_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with session_factory() as db:
            result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
            job = result.scalar_one_or_none()

            if not job:
                logger.error("Job %s não encontrado", job_id)
                return {"error": "Job not found"}

            job.processing_started_at = datetime.now(UTC)
            db.add(JobLog(job_id=job_id, level=LogLevel.INFO, message="Processamento iniciado"))
            await db.commit()

            try:
                if not job.sped_input_s3_key or not job.excel_input_s3_key:
                    raise SpedProcessingError("Arquivo SPED ou planilha Excel não enviados")

                try:
                    sped_path = await storage.ensure_local(job.sped_input_s3_key)
                    excel_path = await storage.ensure_local(job.excel_input_s3_key)
                except FileNotFoundError as exc:
                    raise SpedProcessingError(f"Arquivo não encontrado no storage: {exc}") from exc
                except Exception as exc:
                    raise SpedProcessingError(
                        f"Falha ao acessar arquivo no storage: {exc}"
                    ) from exc

                from app.excel.sefa_parser import parse_sefa_excel
                from app.sped.matcher import match_anticipations
                from app.sped.parser import SpedParser
                from app.sped.writer import SpedEnricher

                db.add(JobLog(job_id=job_id, level=LogLevel.INFO, message="Indexando arquivo SPED"))
                await db.commit()
                try:
                    index = SpedParser().parse(sped_path)
                except Exception as exc:
                    raise SpedProcessingError(f"Falha ao indexar o arquivo SPED: {exc}") from exc

                db.add(JobLog(
                    job_id=job_id, level=LogLevel.INFO,
                    message=f"{len(index.c100_blocks)} nota(s) fiscal(is) encontrada(s) no SPED",
                ))
                await db.commit()

                try:
                    anticipations = parse_sefa_excel(excel_path)
                except Exception as exc:
                    raise SpedProcessingError(f"Falha ao ler a planilha SEFA-PA: {exc}") from exc

                matched, unmatched = match_anticipations(index, anticipations)

                db.add(JobLog(
                    job_id=job_id, level=LogLevel.INFO,
                    message=(
                        f"{len(matched)} antecipação(ões) associada(s), "
                        f"{len(unmatched)} sem correspondência"
                    ),
                ))
                if unmatched:
                    for ant in unmatched:
                        db.add(JobLog(
                            job_id=job_id, level=LogLevel.WARN,
                            message=(
                                f"Sem correspondência no SPED: NF {ant.numero_nf} "
                                f"série {ant.serie} CNPJ {ant.emitente_cnpj} tipo {ant.tipo}"
                            ),
                        ))
                await db.commit()

                if not matched:
                    raise SpedProcessingError(
                        "Nenhuma antecipação da planilha foi associada a uma nota fiscal do SPED"
                    )

                output_key = f"jobs/{job_id}/sped_output.txt"
                output_path = storage.local_path_for(output_key, ensure_parent=True)

                try:
                    sped_result = SpedEnricher().enrich(sped_path, output_path, index, matched)
                except Exception as exc:
                    raise SpedProcessingError(f"Falha ao enriquecer o arquivo SPED: {exc}") from exc

                try:
                    await storage.publish_local(output_key)
                except Exception as exc:
                    raise SpedProcessingError(f"Falha ao publicar SPED de saída: {exc}") from exc

                # AnticipationRecord: uma linha por item, matched e unmatched — dá
                # rastreabilidade por NF, não só os totais agregados do job.
                records = [
                    AnticipationRecord(
                        job_id=job_id,
                        chave_nfe=m.chave_nfe or None,
                        numero_nf=m.numero_nf or None,
                        serie_nf=m.serie or None,
                        emitente_cnpj=m.emitente_cnpj or None,
                        tipo_antecipacao=TipoAntecipacao(m.tipo),
                        valor_icms=m.valor_icms,
                        codigo_ajuste=m.codigo_ajuste_c197,
                        dare_numero=m.dare_numero,
                        dare_vencimento=_parse_ddmmaaaa(m.dare_vencimento),
                        matched=True,
                    )
                    for m in matched
                ]
                records += [
                    AnticipationRecord(
                        job_id=job_id,
                        chave_nfe=ant.chave_nfe or None,
                        numero_nf=ant.numero_nf or None,
                        serie_nf=ant.serie or None,
                        emitente_cnpj=ant.emitente_cnpj or None,
                        tipo_antecipacao=TipoAntecipacao(ant.tipo),
                        valor_icms=ant.valor_icms,
                        codigo_ajuste=None,
                        dare_numero=ant.dare_numero,
                        dare_vencimento=_parse_ddmmaaaa(ant.dare_vencimento),
                        matched=False,
                    )
                    for ant in unmatched
                ]
                db.add_all(records)

                # anticipations_total do ProcessingResult do motor é sempre igual
                # a anticipations_matched (o motor não recebe a lista unmatched) —
                # não copiar isso direto, calcular aqui a partir de match_anticipations.
                job.status = JobStatus.COMPLETED
                job.sped_output_s3_key = output_key
                job.nfs_found = sped_result.nfs_found
                job.anticipations_matched = len(matched)
                job.anticipations_total = len(matched) + len(unmatched)
                job.c197_records_inserted = sped_result.c197_inserted
                job.e111_records_inserted = sped_result.e111_inserted
                job.e116_records_inserted = sped_result.e116_inserted
                job.processing_finished_at = datetime.now(UTC)
                db.add(JobLog(
                    job_id=job_id, level=LogLevel.INFO,
                    message=(
                        f"Processamento concluído: {sped_result.c197_inserted} C197, "
                        f"{sped_result.e111_inserted} E111, "
                        f"{sped_result.e116_inserted} E116 inseridos"
                    ),
                ))
                await db.commit()
                return {"status": "completed", "job_id": job_id}

            except SpedProcessingError as exc:
                job.status = JobStatus.FAILED
                job.error_message = str(exc)
                job.processing_finished_at = datetime.now(UTC)
                db.add(JobLog(job_id=job_id, level=LogLevel.ERROR, message=str(exc)))
                await db.commit()
                logger.warning("Job %s falhou (erro de negócio): %s", job_id, exc)
                return {"status": "failed", "error": str(exc)}
    finally:
        if engine is not None:
            await engine.dispose()


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="process_sped_job",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_sped_job(self: Task, job_id: str) -> dict:
    """Wrapper síncrono da task Celery em torno de run_sped_processing.

    Erros de negócio (arquivo inválido) são tratados DENTRO de
    run_sped_processing e não chegam aqui — só exceções inesperadas (banco
    fora do ar, disco cheio, etc.) escapam e acionam retry do Celery, já que
    essas podem ter sucesso numa nova tentativa.
    """
    import asyncio

    try:
        return asyncio.run(run_sped_processing(job_id))
    except Exception as exc:
        logger.exception("Erro inesperado ao processar job %s", job_id)
        raise self.retry(exc=exc)
