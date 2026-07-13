"""Base de conhecimento por tenant e montagem do system prompt.

O bloco da base de conhecimento leva cache_control (prompt caching):
a primeira chamada paga preço cheio, as seguintes leem do cache a ~10%
do preço de entrada — ver context/custos-ia.md.
"""

from pathlib import Path
from typing import List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy import select

from .config import PROJECT_ROOT
from .models import Document, Organization

RULES = """
REGRAS DE ESCOPO (obrigatórias):
1. Responda apenas com base no conteúdo entre as tags <base_de_conhecimento>.
   Não use conhecimento geral sobre o mundo, outras organizações ou fatos
   externos ao que está documentado ali.
2. Se a pergunta não puder ser respondida com esse conteúdo, diga claramente
   que essa informação não está na sua base de conhecimento atual — não
   invente, não especule.
3. Nunca finja ter tomado uma ação (publicar, enviar, decidir) — você apenas
   informa e sugere, seguindo o princípio "a IA sugere, a equipe decide".
4. Mantenha tom institucional, caloroso e sem hype, conforme o linguajar da
   TeIA.

ESTILO DE CONVERSA (obrigatório):
- Responda como uma pessoa conversando, não como um documento. Escreva em
  parágrafos curtos e corridos, como numa troca de mensagens.
- NÃO use formatação Markdown: nada de títulos (#), negrito (**), itálico,
  listas com hífen ou numeração, tabelas ou blocos de código. O chat exibe
  texto puro, então esses símbolos aparecem literalmente para o usuário.
- Seja direto: comece respondendo a pergunta, sem preâmbulos como "Ótima
  pergunta" ou "Com base na minha base de conhecimento".
- Prefira respostas curtas (2 a 4 parágrafos). Se o assunto tiver muitos
  desdobramentos, responda o essencial e ofereça continuar: "quer que eu
  detalhe X?".
- Se precisar enumerar poucos itens, faça isso dentro da própria frase
  ("são três frentes: educação, cultura e segurança alimentar").
"""


def load_context(context_dir: str) -> str:
    """Concatena os .md da pasta do tenant (relativa à raiz do repositório)."""
    directory = (PROJECT_ROOT / context_dir).resolve()
    # trava de segurança: a pasta precisa estar dentro do repositório
    if PROJECT_ROOT not in directory.parents and directory != PROJECT_ROOT:
        raise ValueError(f"context_dir fora do repositório: {context_dir}")
    parts = []
    for path in sorted(directory.glob("*.md")):
        parts.append(f"### {path.name}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def has_indexed_documents(db, org_id: int) -> bool:
    return bool(db.scalar(
        select(sa_func.count(Document.id)).where(
            Document.organization_id == org_id, Document.status == "indexed"
        )
    ))


def build_system_blocks(org: Organization, db=None,
                        query: Optional[str] = None) -> List[dict]:
    """Blocos de system prompt: regras + base de conhecimento.

    Com documentos indexados, a base vira só os trechos relevantes para a
    pergunta (busca híbrida) — rápido e barato. Sem documentos indexados,
    mantém a pasta concatenada com cache (comportamento original).
    """
    intro = (
        f"Você é o assistente de chat da TeIA a serviço de: {org.name}.\n"
        f"Sua base de conhecimento cobre: {org.description}.\n"
        f"{RULES}"
    )
    if db is not None and query and has_indexed_documents(db, org.id):
        from .kb.search import search_chunks  # tardio: evita ciclo de import

        parts = []
        for hit in search_chunks(db, org.id, query):
            label = hit.filename + (f" · {', '.join(hit.tags)}" if hit.tags else "")
            parts.append(f"[{label}]\n{hit.text}")
        kb = "\n\n---\n\n".join(parts) or (
            "Nenhum trecho da base de conhecimento casou com esta pergunta."
        )
        kb = (
            "Trechos da base de conhecimento selecionados para a pergunta "
            "atual (cada um identificado por [arquivo · tags]):\n\n" + kb
        )
        # sem cache_control: o conteúdo muda a cada pergunta
        return [
            {"type": "text", "text": intro},
            {"type": "text",
             "text": f"<base_de_conhecimento>\n{kb}\n</base_de_conhecimento>"},
        ]
    kb = load_context(org.context_dir)
    return [
        {"type": "text", "text": intro},
        {
            "type": "text",
            "text": f"<base_de_conhecimento>\n{kb}\n</base_de_conhecimento>",
            "cache_control": {"type": "ephemeral"},
        },
    ]
