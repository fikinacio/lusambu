import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

INVOICENINJA_URL = os.getenv("INVOICENINJA_URL", "https://invoices.biscaplus.com")


def _headers() -> dict:
    return {
        "X-Api-Token": os.getenv("INVOICENINJA_API_KEY", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse_valor(valor_str: str) -> float:
    """Extrai valor numérico de string PT. '250.000 Kz/mês' → 250000.0."""
    num = re.sub(r"[^\d.,]", "", valor_str or "")
    # Ponto = separador de milhar (PT); vírgula = decimal
    num = num.replace(".", "").replace(",", ".")
    try:
        return float(num)
    except (ValueError, AttributeError):
        return 0.0


async def get_or_create_client(name: str, email: str) -> str:
    """Pesquisa cliente por email; se não existe, cria. Devolve client_id."""
    async with httpx.AsyncClient(timeout=15, base_url=INVOICENINJA_URL) as client:
        try:
            r = await client.get(
                "/api/v1/clients",
                params={"filter": email},
                headers=_headers(),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if data:
                logger.info(f"Cliente InvoiceNinja encontrado para {email}")
                return data[0]["id"]
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao pesquisar cliente: {e.response.status_code}")
            raise

        try:
            r = await client.post(
                "/api/v1/clients",
                json={"name": name, "contacts": [{"email": email}]},
                headers=_headers(),
            )
            r.raise_for_status()
            client_id = r.json()["data"]["id"]
            logger.info(f"Cliente InvoiceNinja criado: {client_id}")
            return client_id
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao criar cliente: {e.response.status_code}")
            raise


async def create_invoice(client_id: str, valor_str: str, empresa: str) -> dict:
    """Cria factura no InvoiceNinja. Devolve {invoice_id, invoice_number}."""
    valor = _parse_valor(valor_str)
    async with httpx.AsyncClient(timeout=15, base_url=INVOICENINJA_URL) as client:
        try:
            payload = {
                "client_id": client_id,
                "line_items": [{
                    "product_key": "Serviço Digital",
                    "notes": f"Serviço Bisca+ para {empresa} — {valor_str}",
                    "cost": valor,
                    "quantity": 1,
                }],
                "public_notes": "Obrigado pela confiança na Bisca+.",
            }
            r = await client.post("/api/v1/invoices", json=payload, headers=_headers())
            r.raise_for_status()
            inv = r.json()["data"]
            result = {"invoice_id": inv["id"], "invoice_number": inv.get("number", "")}
            logger.info(f"Factura criada: {result['invoice_number']}")
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao criar factura: {e.response.status_code}")
            raise


async def send_invoice_email(invoice_id: str) -> bool:
    """Envia factura ao cliente via email."""
    async with httpx.AsyncClient(timeout=15, base_url=INVOICENINJA_URL) as client:
        try:
            r = await client.post(
                "/api/v1/invoices/bulk",
                json={"action": "email", "ids": [invoice_id]},
                headers=_headers(),
            )
            r.raise_for_status()
            logger.info(f"Factura {invoice_id} enviada por email")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao enviar email de factura {invoice_id}: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar email de factura {invoice_id}: {e}")
            return False


async def send_invoice_reminder(invoice_id: str) -> bool:
    """Reenvia factura ao cliente como reminder de pagamento."""
    async with httpx.AsyncClient(timeout=15, base_url=INVOICENINJA_URL) as client:
        try:
            r = await client.post(
                "/api/v1/invoices/bulk",
                json={"action": "email", "ids": [invoice_id]},
                headers=_headers(),
            )
            r.raise_for_status()
            logger.info(f"Reminder de factura {invoice_id} enviado")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP ao enviar reminder de factura {invoice_id}: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar reminder de factura {invoice_id}: {e}")
            return False
