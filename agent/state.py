from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class LeadInfo(TypedDict, total=False):
    name: Optional[str]
    has_business: Optional[bool]
    company: Optional[str]
    sector: Optional[str]
    pain_point: Optional[str]
    size: Optional[str]
    scheduled_time: Optional[str]   # dia/hora preferida indicada pelo lead para a chamada
    classification: str        # hot | warm | cold | unknown
    is_objecting: bool
    wants_human: bool
    ready_to_close: bool
    confirms_data: bool        # lead respondeu "sim" ao resumo de confirmação (turno actual)


class LusambuState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    whatsapp_number: str
    lead_info: LeadInfo
    stage: str                 # qualify | pitch | objection | closing | discard | escalate | end
    objection_count: int
    turn_count: int
    message_offset: int
    prompt_variant: str
    escalation_reason: str
    fidel_notified: bool
    data_confirmed: bool       # lead confirmou o resumo de dados (sticky — uma vez true, fica true)
    calendly_sent: bool        # link Calendly já foi enviado nesta conversa
    supervisor_decision: dict  # última análise do supervisor de vendas
    sales_agent_active: bool   # Sales Agent tomou conta da conversa
