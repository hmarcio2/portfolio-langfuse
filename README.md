# portfolio-langfuse

Langfuse **self-hosted** (série 4) em Docker para o portfólio: um só servidor de observabilidade para todos os projetos. Fica atrás do Caddy do `portfolio-edge` em `langfuse.SEUDOMINIO`; os apps enviam os traces pela rede interna, sem passar pela internet.

**Status:** testado de verdade em 2026-11-01. O compose subiu os seis serviços (todos `healthy`) numa máquina Windows com Docker Desktop, o Langfuse **4.72.0** respondeu em `localhost:3300`, e os testes de fumaça dos três apps (`evaluation.langfuse_smoke` em `00-site-chat`, `01-recomendador-filmes` e `02-agente-planilhas`) passaram: as observações e as notas chegaram ao servidor. **Não testado:** o modo VPS (Caddy, HTTPS, rede `edge`), o consumo real de memória sob carga e o backup.

**Dois problemas que só apareceram ao subir de verdade** (já corrigidos aqui):
1. **Imagem antiga em cache.** O Docker reaproveita a imagem `:4` que já estiver na máquina; a minha era a 4.30.0 e **rejeitava as notas** que o SDK 5.1 envia em lote (`POST /api/public/scores` com um array; o log do servidor mostrava "expected object, received array"). Os traces chegavam, as notas não. Depois de `docker compose pull`, a 4.72.0 aceitou. Regra: **o servidor precisa ser tão novo quanto o SDK**; rode `docker compose pull` antes de subir e fixe uma versão mínima no seu ambiente.
2. **Healthcheck sempre `unhealthy`** com a imagem nova: o Next.js escuta no `HOSTNAME` do container (o id), não em `127.0.0.1`, e o healthcheck usa o loopback. A correção é `HOSTNAME: 0.0.0.0` no `langfuse-web` (há um teste).

**Para ler os dados por API:** nesta versão (modo "v4 events only") os endpoints antigos `GET /api/public/traces` e `/scores` respondem "not available"; leia pelo SDK (`client.api.scores.get_many`, `client.api.observations.get_many`) ou por `GET /api/public/v2/observations`, como fazem os testes de fumaça.

## Dois modos de uso

- **A. Só local (o padrão por enquanto):** o Docker fica pré-configurado e você sobe quando quiser (`compose.local.yml`, abaixo). Os apps rodam sem Langfuse (sem chaves, o tracing é desligado). As evidências estão em `00-site-chat/docs/observabilidade/` (traces reais exportados, visualizador estático).
- **B. Na VPS de 16 GB, com orçamento de 8 GB:** os seis serviços têm tetos que somam exatamente 8 GiB (`CLICKHOUSE_MEM=3584m`, web 1,5 GB, worker, Postgres 1 GB, Redis e MinIO 0,5 GB); os outros 8 GB ficam para os apps (cerca de 2,5 GB de tetos) e o sistema. `python scripts/check_memory_budget.py` confere a soma e roda no CI e no deploy; subir um teto no `.env` além do orçamento faz o deploy falhar.

## Como funciona

```
 apps (rede "edge")                          langfuse-web ──► postgres   (usuários, projetos, chaves)
 portfolio-chat ──► http://langfuse-web:3000      │      ├──► clickhouse (traces e observações)
 portfolio-filmes                                 │      ├──► redis      (fila)
 portfolio-planilhas                       langfuse-worker├──► minio      (eventos brutos em S3)
 navegador ──► Caddy ──► langfuse.SEUDOMINIO ─────┘
```

- **Só o `langfuse-web` entra na rede `edge`**; Postgres, ClickHouse, Redis e MinIO ficam na rede interna do compose e **nenhuma porta é publicada** no host (o compose oficial publica várias). O Caddy faz o HTTPS.
- **Sem segredos padrão**: o compose oficial traz `mysalt`, `miniosecret`... para facilitar o teste; aqui toda senha é obrigatória (`${VAR:?}`) e vem do `.env` gerado por `scripts/gen_env.py` (aleatórios, permissão 600).
- **Cadastro aberto desligado** (`AUTH_DISABLE_SIGNUP`): numa instância pública, qualquer pessoa poderia criar conta. Entra só o administrador criado no bootstrap e quem você convidar.
- Telemetria do Langfuse desligada; limites de memória por serviço; healthchecks; `restart: unless-stopped`.

## Rodar localmente

```powershell
cd _langfuse
python scripts\gen_env.py --email voce@exemplo.com          # cria o .env; mostra login, senha e as chaves do projeto (uma vez)
docker compose -f compose.yml -f compose.local.yml up -d
docker compose -f compose.yml -f compose.local.yml ps       # espere langfuse-web "healthy" (1ª vez: alguns minutos)
```
Interface em `http://localhost:3300` (porta 3300 para não colidir com o Langfuse do projeto Chatbot, se estiver no ar). Para o chat enviar traces para ele, no `.env` do chat (ou no terminal):

```
LANGFUSE_PUBLIC_KEY=pk-lf-...        # as que o gen_env.py mostrou
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://localhost:3300
```
e confira com `cd ..\00-site-chat; ..\.venv\Scripts\python -m evaluation.langfuse_smoke`.

Parar: `docker compose -f compose.yml -f compose.local.yml down` (os dados ficam nos volumes). Apagar tudo: `down -v`.

## Na VPS (Hostinger)

Pré-requisitos: o `portfolio-edge` já no ar (rede `edge` e Caddy) e um registro DNS `A` para `langfuse.SEUDOMINIO`.

1. Rode `Actions > Deploy` neste repositório. Na primeira vez ele copia os arquivos e para pedindo o `.env`.
2. Na VPS: `cd /opt/apps/langfuse && python3 scripts/gen_env.py --email voce@exemplo.com --domain seudominio.com.br`. Guarde a senha e as chaves que aparecem.
3. Rode o deploy de novo. O primeiro start leva alguns minutos (migrações do Postgres e do ClickHouse); o deploy espera o `healthy` (até 10 min).
4. Nos `.env` dos apps na VPS: `LANGFUSE_BASE_URL=http://langfuse-web:3000` (rede interna) e as chaves do projeto de cada app.

### Quanto de VPS isso pede? (plano: VPS de 16 GB)
O Langfuse v3/v4 é pesado: fontes de terceiros dão 4 GB e 2 vCPU como mínimo e 8 a 16 GB como recomendado, e um guia fala em 8 GiB só para o ClickHouse. Os números abaixo são **tetos configurados no compose, não consumo medido**; meça com `docker stats` depois de subir.

| Serviço | Teto padrão | Sugestão p/ 16 GB (`.env`) |
|---|---|---|
| ClickHouse | 3 GB | `CLICKHOUSE_MEM=4g` |
| langfuse-web | 1,5 GB | `WEB_MEM=2g` |
| langfuse-worker | 1 GB | `WORKER_MEM=1536m` |
| Postgres | 1 GB | `POSTGRES_MEM=1g` |
| Redis + MinIO | 0,5 GB + 0,5 GB | padrão |
| **Langfuse (soma dos tetos)** | **7,5 GB** | **9,5 GB** |
| Apps (chat 512 MB, filmes 768 MB, planilhas 1 GB, site 128 MB) + Caddy | ~2,5 GB | |
| Sistema operacional e margem | ~1,5 GB | |
| **Total com a sugestão** | | **~13,5 GB de 16 GB** |

Se o `docker stats` mostrar o ClickHouse perto do teto, suba o `CLICKHOUSE_MEM` (ele é o que mais cresce com o volume de traces); se a VPS apertar, o **Langfuse Cloud** (plano gratuito) em produção, com este Docker só para desenvolvimento, é a saída.

## Um Langfuse para todos os projetos?

**Sim.** Uma instância atende todos; o que muda é como organizar. O modelo do Langfuse é:

```
Organização "Portfolio"
 ├─ Projeto portfolio-chat        ← chaves próprias, dados próprios
 ├─ Projeto portfolio-filmes
 ├─ Projeto portfolio-planilhas
 └─ Projeto chatbot               ← o seu outro projeto também cabe aqui
        dentro de cada projeto:  environment · tags · nome do trace · sessão · release · metadata
```

**Não existem "subprojetos" (projetos aninhados).** Projeto é o nível mais baixo de isolamento; abaixo dele você agrupa por campos do trace:

| Quero separar... | Use | Exemplo |
|---|---|---|
| apps diferentes | **um projeto por app** (recomendado) | `portfolio-chat`, `portfolio-filmes` |
| produção, desenvolvimento, testes | **environment** (`LANGFUSE_TRACING_ENVIRONMENT`) | `production`, `development`, `portfolio-smoke` |
| partes/funcionalidades de um app | **tags** e **nome do trace** | tags `["portfolio-chat", "rag"]`, trace `chat-turn` |
| conversas | **session_id** | o id da sessão do chat |
| versões do código | **release** (`PORTFOLIO_RELEASE`) | `v0.3.0` |

**Por que um projeto por app, e não tudo num projeto só com uma tag `app`:**
- **Isolamento de chaves.** As chaves do Langfuse também **leem** os dados do projeto. O chat é público e guarda uma chave no servidor; se ela vazar, só expõe o projeto do chat, não as planilhas dos outros apps.
- **Dados com sensibilidade diferente.** O agente de planilhas pode ter trechos de planilhas de visitantes nos traces; o chat tem perguntas sobre currículo. Separados, dá para ter retenção e acesso diferentes.
- **Painéis e custos por app** sem filtros.

**O que se perde:** não há painel único que some todos os projetos (cada um tem o seu). Se isso for importante, a alternativa é um projeto único com tags (`app:chat`, `app:filmes`), mais simples de comparar e com menos isolamento. Dá para começar separado e unificar depois por exportação.

**Como criar** (interface, logado como administrador): Organização > Projects > New project > Settings > API Keys > Create. Cada app recebe o **par de chaves do próprio projeto** no `.env` (com `LANGFUSE_BASE_URL=http://langfuse-web:3000`). O bootstrap cria só o primeiro projeto; os outros são criados na interface.

> Observação: descrevo o modelo do Langfuse (organização, projeto, environment, tags, sessões) a partir da documentação que conheço e do SDK 5.1 instalado; recursos de permissão por projeto ou limite de projetos podem depender da edição e da versão: confirme na interface da sua instância.

## Operação

- **Backup:** o que importa são os volumes `langfuse_postgres_data` (projetos, chaves, usuários), `langfuse_clickhouse_data` (traces) e `langfuse_minio_data` (eventos brutos). Mínimo viável: `docker compose exec postgres pg_dump -U postgres postgres > backup.sql` (projetos e chaves) e snapshot da VPS para o resto. **Guarde o `.env`**: sem o `ENCRYPTION_KEY` os segredos salvos não abrem.
- **Atualizar:** as tags são `:4` (série); `docker compose pull && docker compose up -d --wait` aplica as migrações. Leia as notas de versão do Langfuse antes de subir de série (`:5`) e faça backup. O Postgres está fixo na `17` (`POSTGRES_VERSION`): troca de versão maior exige migração dos dados.
- **Retenção:** os traces crescem; defina a retenção do projeto na interface se for guardar conversas de visitantes (LGPD).
- **Segurança:** a interface fica pública em `langfuse.SEUDOMINIO`; use senha forte, não convide quem não precisa e considere restringir por IP no Caddy se só você acessa.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `compose.yml` | Produção: 6 serviços, rede `edge` só no web, sem portas publicadas |
| `compose.local.yml` | Desenvolvimento: UI em `127.0.0.1:3300`, sem a rede `edge` |
| `scripts/gen_env.py` | Gera o `.env` com segredos aleatórios; nunca sobrescreve sem `--force` |
| `deploy/langfuse.caddy` | Trecho do Caddy (`langfuse.SEUDOMINIO`), instalado pelo deploy |
| `.github/workflows/` | CI (testes + `compose config`) e deploy manual |
| `tests/` | 9 testes: força dos segredos, não sobrescrever, o compose e o gerador concordam, sem portas publicadas, só o web na `edge` |
