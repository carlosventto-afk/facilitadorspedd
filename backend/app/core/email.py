"""Envio de e-mail via SendGrid (API REST direta, sem SDK — mesmo padrão de
app/api/v1/routes/firms.py::lookup_cnpj para chamadas HTTP a terceiros).

Sem SENDGRID_API_KEY configurada (ambiente de dev sem chave real), o envio é
pulado e o conteúdo fica só no log — permite testar o fluxo (ex. reset de
senha) sem depender de e-mail de verdade, sem quebrar silenciosamente em
produção quando a chave estiver configurada.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


async def send_email(to: str, subject: str, html_content: str) -> None:
    if not settings.SENDGRID_API_KEY:
        logger.warning(
            "SENDGRID_API_KEY não configurada — e-mail não enviado. Para: %s | Assunto: %s\n%s",
            to, subject, html_content,
        )
        return

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": settings.EMAIL_FROM},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }
    headers = {
        "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(_SENDGRID_URL, json=payload, headers=headers)
        except httpx.RequestError as exc:
            logger.error("Erro de rede ao enviar e-mail via SendGrid para %s: %s", to, exc)
            return

    if resp.status_code >= 300:
        logger.error(
            "SendGrid retornou %d ao enviar e-mail para %s: %s", resp.status_code, to, resp.text
        )
