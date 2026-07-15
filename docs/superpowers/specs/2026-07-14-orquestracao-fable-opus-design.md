# Orquestração Fable → Opus (coordinator/worker)

Data: 2026-07-14 · Status: aprovado

## Objetivo

Quando uma demanda complexa chega à sessão principal (Fable), ele orquestra: decompõe, delega as tasks simples a workers rodando em Opus e mantém para si o raciocínio complexo. Reduz custo (Opus executa o braçal) sem perder qualidade (Fable planeja e revisa).

Restrição técnica que define o formato: no Claude Code, subagente não dispara subagente — a ferramenta `Agent` só existe na sessão principal. Logo o coordinator é o próprio Fable na sessão principal, não um subagente.

## Componentes

1. **`.claude/agents/executor-opus.md`** — worker genérico com `model: opus` e todas as ferramentas. System prompt em pt-BR com as normas que um worker "frio" precisa: executa uma task exatamente como escopada (sem expandir escopo), código/commits em inglês e docs em pt-BR, `py` no Windows, nunca `cd` persistente (subshell), economia de tokens, isolamento entre tenants como invariante nº 1. Não commita; devolve relatório (o que mudou, arquivos, como verificar).

2. **Seção "Orquestração de demandas complexas" no CLAUDE.md** — regra automática:
   - Gatilho: demanda que se decompõe em **3+ tasks independentes e bem definidas**.
   - Fable mantém para si tasks de raciocínio complexo (arquitetura, segurança, decisões) e despacha as simples ao `executor-opus` em paralelo, com prompts auto-contidos (paths, contexto, critério de aceite).
   - Ao receber resultados: revisão crítica (correção, isolamento multi-tenant, padrões do repo), correção do necessário, integração e só então reporte.
   - Fora do gatilho (menos de 3 tasks, ou tasks encadeadas): Fable executa direto.

## Fora de escopo

- Skill de invocação explícita (decidiu-se pelo gatilho automático).
- Workers especializados por tipo (um worker genérico basta; especializar depois se houver necessidade real).
