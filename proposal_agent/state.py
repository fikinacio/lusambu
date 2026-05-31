from typing import Optional
from typing_extensions import TypedDict


class ProposalState(TypedDict, total=False):
    draft_id: str            # UUID em proposal_drafts; preenchido após save
    whatsapp: str            # número do lead
    empresa: str
    sector: str
    dores: str               # dores_identificadas / pain_point
    notas_sales: str         # notas do Sales Agent
    valor_negociado: str     # ex: "250.000 Kz/mês"
    company_config: dict     # dados de company_config (company_name, nif, etc.)
    proposal_text: str       # texto gerado pelo LLM
    fidel_decision: str      # "aprovar" | "editar" | "rejeitar"
    edit_notes: str          # correcções do Fidel (quando fidel_decision == "editar")
    iteration: int           # contador de regenerações
