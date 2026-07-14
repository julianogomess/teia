# Plano de implantação em produção (AWS, custo baixo)

Plano acordado em 2026-07-13, logo após a conclusão da fase 1 da base de
conhecimento indexada. Objetivo: colocar o servidor (`server/`) em produção
com o menor custo que não comprometa segurança nem backup, crescendo em
fases conforme a demanda provar necessidade.

## Restrição que molda o plano: instância única

O servidor hoje assume **um único processo**:

- rate limiting em memória ([app/rate_limit.py](../server/app/rate_limit.py));
- cache de embeddings da busca em memória ([app/kb/search.py](../server/app/kb/search.py));
- worker de ingestão como thread do próprio processo ([app/kb/worker.py](../server/app/kb/worker.py)).

Isso não é um defeito para o estágio atual: uma instância vertical atende
milhares de usuários de chat, e os pontos de troca para escala horizontal
(Redis, worker separado) já estão isolados atrás de interfaces. O plano
abraça a instância única até a fase 2.

## Checklist de preparação (independe de nuvem)

1. **Endurecer a configuração**: `TEIA_SECRET_KEY` forte,
   `TEIA_COOKIE_SECURE=true`, `TEIA_AUTO_CREATE_TABLES=false` e migrations
   via `alembic upgrade head` (tudo suportado em
   [app/config.py](../server/app/config.py)).
2. **HTTPS atrás de proxy reverso** — preferir **Caddy** (TLS automático com
   Let's Encrypt, zero manutenção de certificado) ao
   [nginx.example.conf](../server/nginx.example.conf), que fica como
   referência.
3. **Teto de custo nas APIs**: spend limit na console da Anthropic (por
   workspace/tenant, alinhado à soberania de cobrança) e na Voyage — última
   linha de defesa além das cotas que o servidor já aplica.
4. **Backup de duas coisas**: o Postgres **e** a pasta `server/uploads/`
   (originais dos documentos da base de conhecimento). Perder o disco sem
   backup apaga a base dos clientes.
5. **Google OAuth**: registrar a redirect URI de produção.
6. **Pré-requisito antes de dar login de admin a clientes**: escopar as
   rotas globais de [app/routers/admin.py](../server/app/routers/admin.py)
   por tenant (hoje qualquer `admin` vê todos os tenants; trabalho em
   andamento em sessão própria).

## Fase 0 — validação (~US$ 12–15/mês)

Uma instância **Lightsail de 2 GB** (US$ 10/mês, tráfego incluso) rodando
Docker Compose com três containers:

| Container | Papel |
|---|---|
| app (uvicorn) | o servidor FastAPI |
| Postgres 16 | o mesmo do docker-compose atual, com volume |
| Caddy | HTTPS automático na frente do app |

- IP estático: grátis. Snapshot automático diário: ~US$ 1–2/mês.
  Zona DNS (Route 53): ~US$ 0,50/mês.
- Os 2 GB de RAM importam: cache de embeddings (numpy) e Postgres moram no
  mesmo host.
- Deploy: `git pull && docker compose up -d`; automatizável depois com
  GitHub Actions via SSH.

## Fase 1 — primeiros clientes pagantes (~US$ 40–60/mês)

Quando houver dado de cliente que não pode se perder, separar o estado do
processamento:

- **RDS Postgres db.t4g.micro** (~US$ 15–20/mês com storage): backups
  automáticos de 7 dias, restore point-in-time, patching gerenciado. Bônus:
  o RDS suporta `pgvector` — a otimização de busca da fase 2 fica a um
  `CREATE EXTENSION` de distância, sem serviço novo.
- **EC2 t4g.small** (~US$ 12/mês) para o app.
- **S3** para os originais de `uploads/` (sincronização; centavos/mês).
- **SSM Parameter Store** para os segredos (grátis no tier padrão), saindo
  do `.env`.
- **Alarme de billing** no CloudWatch.

## Fase 2 — só quando a demanda provar (~US$ 100+/mês)

Múltiplas instâncias atrás de um ALB exigem as trocas já mapeadas:

- rate limiting para **Redis** (ElastiCache serverless), mantendo a
  interface de [app/rate_limit.py](../server/app/rate_limit.py);
- worker de ingestão como **processo separado** (o código já isola isso em
  [app/kb/worker.py](../server/app/kb/worker.py));
- busca vetorial no **pgvector** do RDS (mesma interface
  `search_chunks()`), aposentando o cache por instância.

Antes de chegar aqui, subir de t4g.small para t4g.medium resolve
crescimento por ~US$ 12/mês a mais.

## O que NÃO usar agora (mesmo sendo "o jeito AWS")

- **App Runner / Fargate**: sem disco persistente para `uploads/` e podem
  escalar para N instâncias — quebram as premissas de instância única.
- **Aurora Serverless**: custo mínimo bem acima do RDS micro para o volume
  atual.

## Perspectiva de custo

O maior custo de produção não será infraestrutura — será **token de
modelo**, e é o que a base de conhecimento indexada ataca: com retrieval de
top-8 chunks, uma pergunta custa fração de centavo mesmo com base grande, e
as cotas por tenant limitam o pior caso. Ver
[context/custos-ia.md](../context/custos-ia.md).

## Próximo passo concreto

Escrever o compose de produção (app + Caddy + Postgres com volumes e rotina
de backup) e o guia de deploy passo a passo da fase 0.
