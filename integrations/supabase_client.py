import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_KEY", ""),
        )
    return _supabase


_TRANSIENT_FIELDS = {"confirms_data"}  # campos do LLM que não existem como colunas no DB


async def upsert_lead(lead_data: dict) -> bool:
    """Insere ou actualiza lead na tabela lusambu_leads. Chave: 'whatsapp'."""
    try:
        db = get_supabase()
        clean_data = {k: v for k, v in lead_data.items() if v is not None and k not in _TRANSIENT_FIELDS}
        clean_data["last_contact_at"] = datetime.now(timezone.utc).isoformat()
        db.table("lusambu_leads").upsert(clean_data, on_conflict="whatsapp").execute()
        logger.info(f"Lead guardado: {clean_data.get('whatsapp', '—')}")
        return True
    except Exception as e:
        logger.error(f"Erro ao guardar lead: {e}")
        return False


async def get_stale_leads(hours: int = 24) -> list[dict]:
    """Leads activos sem resposta há mais de `hours` horas, com menos de 2 follow-ups."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, sector, stage, followup_count")
            .lt("last_contact_at", cutoff)
            .lt("followup_count", 2)
            .neq("status", "descartado")
            .neq("status", "escalado")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar leads para follow-up: {e}")
        return []


async def get_all_leads() -> list[dict]:
    """Todos os leads ordenados por último contacto."""
    try:
        db = get_supabase()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, company, sector, classification, stage, status, pain_point, followup_count, last_contact_at, prompt_variant")
            .order("last_contact_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar leads: {e}")
        return []


async def get_outreach_message(number: str) -> Optional[str]:
    """Busca a última mensagem outbound enviada a este número via WhatsApp.

    Fluxo: empresas.whatsapp = number → mensagens.empresa_id
    Filtra: direcao='saida', canal='whatsapp'. Devolve mensagens.conteudo.
    """
    try:
        db = get_supabase()
        # 1. Encontrar empresa pelo número de WhatsApp
        empresa = (
            db.table("empresas")
            .select("id")
            .eq("whatsapp", number)
            .limit(1)
            .execute()
        )
        if not empresa.data:
            return None
        empresa_id = empresa.data[0]["id"]
        # 2. Buscar última mensagem outbound enviada a essa empresa
        result = (
            db.table("mensagens")
            .select("conteudo")
            .eq("empresa_id", empresa_id)
            .eq("direcao", "saida")
            .eq("canal", "whatsapp")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("conteudo")
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar contexto de prospecção para {number}: {e}")
        return None


async def get_mensagens_history(number: str, limit: int = 20) -> list[dict]:
    """Busca histórico completo de mensagens (entrada e saída) para este número via WhatsApp.

    Fluxo: empresas.whatsapp = number → mensagens.empresa_id
    Filtra: canal='whatsapp'. Ordena por timestamp ASC.
    Devolve lista de {"direcao": "entrada"|"saida", "conteudo": str}.
    """
    try:
        db = get_supabase()
        empresa = (
            db.table("empresas")
            .select("id")
            .eq("whatsapp", number)
            .limit(1)
            .execute()
        )
        if not empresa.data:
            return []
        empresa_id = empresa.data[0]["id"]
        result = (
            db.table("mensagens")
            .select("direcao, conteudo, timestamp")
            .eq("empresa_id", empresa_id)
            .eq("canal", "whatsapp")
            .order("timestamp", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar histórico de mensagens para {number}: {e}")
        return []


# ---------------------------------------------------------------------------
# Contexto de prospecção: tabela `prospects` + histórico via `empresas`/`mensagens`
# ---------------------------------------------------------------------------

def _whatsapp_variants(number: str) -> list[str]:
    """Gera variantes de um número de WhatsApp para tolerar formatos diferentes.

    O webhook normaliza para dígitos sem '+' (ex: '244923943262'), mas o CRM
    guarda frequentemente com '+' (ex: '+244923943262') ou sem prefixo de país.
    """
    n = (number or "").strip().replace(" ", "").replace("-", "").lstrip("+")
    if not n:
        return []
    local = n[3:] if n.startswith("244") else n
    candidates = {n, f"+{n}", local, f"+{local}", f"244{local}", f"+244{local}"}
    return [v for v in candidates if v]


_PROSPECT_FIELDS = (
    "id, prospect_id, company_name, empresa_nome, sector, nicho, "
    "pain_angle, pain_note, bmst_service, decisor_nome, decisor_cargo, "
    "primary_channel, status, whatsapp, whatsapp_business"
)


async def get_prospect_context(whatsapp_number: str) -> Optional[dict]:
    """Identifica o prospect pelo número de WhatsApp na tabela `prospects`.

    Procura em `whatsapp` ou `whatsapp_business`, tolerando variações de formato.
    Devolve os campos de contexto do prospect, ou None se não encontrado.
    """
    try:
        variants = _whatsapp_variants(whatsapp_number)
        if not variants:
            return None
        db = get_supabase()
        conds = []
        for v in variants:
            conds.append(f"whatsapp.eq.{v}")
            conds.append(f"whatsapp_business.eq.{v}")
        result = (
            db.table("prospects")
            .select(_PROSPECT_FIELDS)
            .or_(",".join(conds))
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar prospect para {whatsapp_number}: {e}")
        return None


async def _resolve_empresa(whatsapp_number: str, prospect_id: Optional[str]) -> Optional[dict]:
    """Resolve a empresa ({id, prospect_id}) para um número/prospect.

    Tenta primeiro por `empresas.whatsapp` (tolerando formatos); se falhar e houver
    `prospect_id`, liga via `empresas.prospect_id`. Devolve o registo ou None.
    """
    try:
        db = get_supabase()
        variants = _whatsapp_variants(whatsapp_number)
        if variants:
            conds = [f"whatsapp.eq.{v}" for v in variants]
            result = (
                db.table("empresas")
                .select("id, prospect_id")
                .or_(",".join(conds))
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        if prospect_id:
            result = (
                db.table("empresas")
                .select("id, prospect_id")
                .eq("prospect_id", prospect_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Erro ao resolver empresa para {whatsapp_number}: {e}")
        return None


async def get_prospect_by_id(prospect_id: str) -> Optional[dict]:
    """Busca o contexto do prospect pelo `prospect_id` (ligação via `empresas`).

    Usado quando o número está guardado em `empresas` mas não em `prospects`.
    """
    try:
        db = get_supabase()
        result = (
            db.table("prospects")
            .select(_PROSPECT_FIELDS)
            .eq("prospect_id", prospect_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Erro ao carregar prospect por id {prospect_id}: {e}")
        return None


async def get_message_history(empresa_id: str) -> list[dict]:
    """Histórico completo de mensagens de uma empresa, ordenado por timestamp ASC.

    Devolve lista de {direcao, canal, conteudo, agente, timestamp} a partir da
    tabela `mensagens` filtrando por `empresa_id`.
    """
    try:
        db = get_supabase()
        result = (
            db.table("mensagens")
            .select("direcao, canal, conteudo, agente, timestamp")
            .eq("empresa_id", empresa_id)
            .order("timestamp", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar histórico de mensagens (empresa_id={empresa_id}): {e}")
        return []


async def increment_followup(whatsapp: str) -> None:
    """Regista o follow-up enviado e actualiza o timestamp."""
    try:
        db = get_supabase()
        db.rpc("increment_followup_count", {"p_whatsapp": whatsapp}).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar followup_count para {whatsapp}: {e}")


async def get_outbound_stale_leads(followup_count: int, hours: int) -> list[dict]:
    """Leads outbound (status='enviado') sem resposta há mais de `hours` horas, com followup_count exacto."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, sector, pain_point, followup_count")
            .eq("status", "enviado")
            .eq("followup_count", followup_count)
            .lt("last_contact_at", cutoff)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar outbound stale leads (count={followup_count}): {e}")
        return []


async def get_company_config() -> dict:
    """Lê todos os pares chave-valor de company_config e devolve como dict."""
    try:
        db = get_supabase()
        result = db.table("company_config").select("key, value").execute()
        return {row["key"]: row["value"] for row in (result.data or [])}
    except Exception as e:
        logger.error(f"Erro ao carregar company_config: {e}")
        return {}


async def get_lead_for_proposal(whatsapp: str) -> Optional[dict]:
    """Lê dados completos do lead para gerar proposta."""
    try:
        db = get_supabase()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, company, sector, pain_point, notas_sales, valor_negociado, status")
            .eq("whatsapp", whatsapp)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao ler lead para proposta ({whatsapp}): {e}")
        return None


async def save_proposal_draft(data: dict) -> Optional[str]:
    """Insere rascunho de proposta. Devolve o UUID gerado."""
    try:
        db = get_supabase()
        result = db.table("proposal_drafts").insert(data).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Erro ao guardar rascunho de proposta: {e}")
        return None


async def update_proposal_draft(draft_id: str, updates: dict) -> None:
    """Actualiza campos de um rascunho existente."""
    try:
        db = get_supabase()
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.table("proposal_drafts").update(payload).eq("id", draft_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar rascunho {draft_id}: {e}")


async def get_pending_proposal_for_fidel() -> Optional[dict]:
    """Devolve o rascunho mais recente em estado pending ou editing."""
    try:
        db = get_supabase()
        result = (
            db.table("proposal_drafts")
            .select("*")
            .in_("status", ["pending", "editing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar proposta pendente: {e}")
        return None


# ---------------------------------------------------------------------------
# Invoice drafts
# ---------------------------------------------------------------------------

async def get_lead_for_invoice(whatsapp: str) -> Optional[dict]:
    """Lê dados completos do lead para gerar factura (inclui email)."""
    try:
        db = get_supabase()
        result = (
            db.table("lusambu_leads")
            .select("whatsapp, name, company, sector, email, valor_negociado, status")
            .eq("whatsapp", whatsapp)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao ler lead para factura ({whatsapp}): {e}")
        return None


async def save_invoice_draft(data: dict) -> Optional[str]:
    """Insere rascunho de factura. Devolve o UUID gerado."""
    try:
        db = get_supabase()
        result = db.table("invoice_drafts").insert(data).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Erro ao guardar rascunho de factura: {e}")
        return None


async def update_invoice_draft(draft_id: str, updates: dict) -> None:
    """Actualiza campos de um rascunho de factura existente."""
    try:
        db = get_supabase()
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.table("invoice_drafts").update(payload).eq("id", draft_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar rascunho de factura {draft_id}: {e}")


async def get_pending_invoice_for_fidel() -> Optional[dict]:
    """Devolve o rascunho de factura mais recente em estado pending ou editing."""
    try:
        db = get_supabase()
        result = (
            db.table("invoice_drafts")
            .select("*")
            .in_("status", ["pending", "editing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar factura pendente: {e}")
        return None


async def get_overdue_invoices(days: int, alerted_field: str) -> list[dict]:
    """Facturas enviadas sem pagamento há mais de `days` dias, ainda não alertadas."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            db.table("invoice_drafts")
            .select("id, whatsapp, empresa, invoice_id, invoice_number, data_faturacao")
            .eq("status_pagamento", "pendente")
            .lt("data_faturacao", cutoff)
            .eq(alerted_field, False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar facturas em atraso ({days}d): {e}")
        return []


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def get_deal_for_project(whatsapp: str) -> Optional[dict]:
    """Lê dados do deal: invoice_drafts (valor/empresa/sector/email) + lusambu_leads (name)."""
    try:
        db = get_supabase()
        inv = (
            db.table("invoice_drafts")
            .select("whatsapp, empresa, sector, email, valor")
            .eq("whatsapp", whatsapp)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not inv.data:
            return None
        deal = dict(inv.data[0])
        lead = (
            db.table("lusambu_leads")
            .select("name")
            .eq("whatsapp", whatsapp)
            .limit(1)
            .execute()
        )
        deal["contact_name"] = lead.data[0].get("name", "") if lead.data else ""
        return deal
    except Exception as e:
        logger.error(f"Erro ao ler deal para projecto ({whatsapp}): {e}")
        return None


async def save_project(data: dict) -> Optional[str]:
    """Insere registo de projecto. Devolve o UUID gerado."""
    try:
        db = get_supabase()
        result = db.table("projects").insert(data).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Erro ao guardar projecto: {e}")
        return None


async def update_project(project_id: str, updates: dict) -> None:
    """Actualiza campos de um projecto existente."""
    try:
        db = get_supabase()
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.table("projects").update(payload).eq("id", project_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar projecto {project_id}: {e}")


async def get_project_by_whatsapp(whatsapp: str) -> Optional[dict]:
    """Devolve o projecto activo (em_curso) mais recente para este número."""
    try:
        db = get_supabase()
        result = (
            db.table("projects")
            .select("*")
            .eq("whatsapp", whatsapp)
            .eq("status", "em_curso")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar projecto para {whatsapp}: {e}")
        return None


async def get_draft_project_for_fidel() -> Optional[dict]:
    """Devolve o projecto em draft mais recente (aguardando aprovação do Fidel)."""
    try:
        db = get_supabase()
        result = (
            db.table("projects")
            .select("*")
            .eq("status", "draft")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar projecto draft para Fidel: {e}")
        return None


async def save_project_milestones(project_id: str, milestones: list) -> None:
    """Insere lista de milestones para um projecto."""
    try:
        db = get_supabase()
        rows = [{"project_id": project_id, **m} for m in milestones]
        db.table("project_milestones").insert(rows).execute()
    except Exception as e:
        logger.error(f"Erro ao guardar milestones do projecto {project_id}: {e}")


async def get_project_milestones(project_id: str) -> list[dict]:
    """Devolve todos os milestones de um projecto ordenados por ordem."""
    try:
        db = get_supabase()
        result = (
            db.table("project_milestones")
            .select("*")
            .eq("project_id", project_id)
            .order("ordem")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao carregar milestones do projecto {project_id}: {e}")
        return []


async def update_milestone(milestone_id: str, updates: dict) -> None:
    """Actualiza campos de um milestone existente."""
    try:
        db = get_supabase()
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.table("project_milestones").update(payload).eq("id", milestone_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar milestone {milestone_id}: {e}")


async def get_delayed_milestones() -> list[dict]:
    """Milestones com data_prevista passada, não concluídos, de projectos em curso."""
    try:
        db = get_supabase()
        today = datetime.now(timezone.utc).date().isoformat()
        result = (
            db.table("project_milestones")
            .select("id, project_id, nome, data_prevista")
            .lt("data_prevista", today)
            .neq("status", "concluido")
            .neq("status", "atrasado")
            .execute()
        )
        rows = []
        for m in (result.data or []):
            proj = (
                db.table("projects")
                .select("whatsapp, empresa, notion_page_id")
                .eq("id", m["project_id"])
                .eq("status", "em_curso")
                .limit(1)
                .execute()
            )
            if proj.data:
                rows.append({**m, **proj.data[0]})
        return rows
    except Exception as e:
        logger.error(f"Erro ao buscar milestones atrasados: {e}")
        return []


async def get_completed_milestones_pending_confirmation() -> list[dict]:
    """Milestones concluídos que ainda não foram confirmados ao Fidel."""
    try:
        db = get_supabase()
        result = (
            db.table("project_milestones")
            .select("id, project_id, nome, ordem")
            .eq("status", "concluido")
            .eq("fidel_alerted_completion", False)
            .execute()
        )
        rows = []
        for m in (result.data or []):
            proj = (
                db.table("projects")
                .select("whatsapp, empresa, email, canal_preferido, notion_page_id, contact_name")
                .eq("id", m["project_id"])
                .eq("status", "em_curso")
                .limit(1)
                .execute()
            )
            if proj.data:
                rows.append({**m, **proj.data[0]})
        return rows
    except Exception as e:
        logger.error(f"Erro ao buscar milestones concluídos pendentes: {e}")
        return []


async def get_pending_project_event_for_fidel() -> Optional[dict]:
    """Devolve o event de projecto mais recente em estado pending."""
    try:
        db = get_supabase()
        result = (
            db.table("project_events")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        event = dict(result.data[0])
        proj = (
            db.table("projects")
            .select("whatsapp, empresa, email, canal_preferido, notion_page_id, contact_name")
            .eq("id", event["project_id"])
            .limit(1)
            .execute()
        )
        if proj.data:
            event.update(proj.data[0])
        return event
    except Exception as e:
        logger.error(f"Erro ao buscar event de projecto pendente: {e}")
        return None


async def save_project_event(data: dict) -> Optional[str]:
    """Insere event de projecto. Devolve o UUID gerado."""
    try:
        db = get_supabase()
        result = db.table("project_events").insert(data).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Erro ao guardar event de projecto: {e}")
        return None


async def update_project_event(event_id: str, updates: dict) -> None:
    """Actualiza campos de um event de projecto existente."""
    try:
        db = get_supabase()
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.table("project_events").update(payload).eq("id", event_id).execute()
    except Exception as e:
        logger.error(f"Erro ao actualizar event {event_id}: {e}")
