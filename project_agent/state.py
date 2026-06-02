from typing import TypedDict


class ProjectState(TypedDict, total=False):
    whatsapp: str
    empresa: str
    servico_tipo: str
    valor: float
    contact_name: str
    email: str
    canal_preferido: str       # "whatsapp" | "email"
    company_config: dict
    milestones: list           # [{"nome": str, "ordem": int, "data_prevista": "YYYY-MM-DD"}]
    milestones_preview: str    # texto formatado WhatsApp
    edit_notes: str
    fidel_decision: str        # "aprovar" | "editar"
    iteration: int
    notion_page_id: str
    project_id: str            # UUID em projects
