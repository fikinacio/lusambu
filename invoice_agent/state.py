from typing_extensions import TypedDict


class InvoiceState(TypedDict, total=False):
    whatsapp: str            # número do lead
    empresa: str
    sector: str
    email: str               # email do cliente para envio da factura
    valor_negociado: str     # ex: "250.000 Kz/mês"
    company_config: dict     # dados de company_config
    invoice_preview: str     # pré-visualização gerada pelo LLM
    edit_notes: str          # correcções do Fidel (quando fidel_decision == "editar")
    fidel_decision: str      # "aprovar" | "editar" | "rejeitar"
    iteration: int           # contador de regenerações
    client_id: str           # InvoiceNinja client ID
    invoice_id: str          # InvoiceNinja invoice ID
    invoice_number: str      # número humano da factura
    invoice_draft_id: str    # UUID em invoice_drafts
    notion_page_url: str     # URL da página criada no Notion
