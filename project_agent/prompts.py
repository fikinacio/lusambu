PROJECT_MILESTONES_PROMPT = """\
És o gestor de projecto da {company_name}, empresa de tecnologia e IA.

O cliente *{empresa}* contratou o serviço *{servico_tipo}*.
Data de início: {data_inicio}

Plano de milestones gerado:
{milestones_json}

Formata este plano como uma mensagem WhatsApp clara e profissional.
Usa *negrito* para o título do projecto e para cada milestone.
Inclui a data prevista de cada milestone.
Devolve apenas o texto formatado, sem introduções ou explicações.\
"""

PROJECT_EDIT_PROMPT = """\
Revê o seguinte plano de projecto e aplica as correcções pedidas.

Plano actual:
{milestones_preview}

Correcções pedidas:
{edit_notes}

Devolve o plano corrigido no mesmo formato WhatsApp, sem mais nenhum texto.\
"""

WELCOME_MESSAGE = """\
Olá {nome}!

O pagamento foi confirmado e o projecto arranca hoje.

Nos próximos dias vou partilhar convosco o plano detalhado \
com as datas de cada entrega.

Qualquer dúvida estou disponível por aqui.

Fidel Kussunga | Bisca+\
"""

APPROVAL_BUTTONS_2 = [
    {"buttonId": "aprovar", "buttonText": {"displayText": "✅ Aprovar"}},
    {"buttonId": "editar",  "buttonText": {"displayText": "✏️ Editar"}},
]
