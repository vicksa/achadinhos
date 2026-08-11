# Achadinhos 🔥

Bot que coleta ofertas e promoções de e-commerce brasileiro (Amazon, Mercado
Livre, Magalu, Pichau, Americanas, Casas Bahia, Netshoes, AliExpress etc.) e
publica automaticamente em um canal do Telegram, com card visual gerado na
hora e filtro por desconto mínimo.

## Como funciona

```
scrapers/pelando_scraper.py   ─┐
scrapers/promobit_scraper.py  ─┼─► bot/scheduler.py (a cada N min)
                                │        │
                                │        ├─ bot/dedup.py         (evita repostar)
                                │        ├─ core/models.py Deal  (salva no Postgres)
                                │        ├─ bot/card_generator.py (gera imagem PNG)
                                │        └─ bot/telegram_publisher.py (posta no canal)
```

As ofertas não vêm de uma única loja — vêm de dois agregadores (Pelando e
Promobit) que já cobrem dezenas de lojas brasileiras, incluindo as que você
citou (Pichau, Magalu, Americanas). Scraping direto de cada loja individual
não foi implementado de propósito: essas lojas mudam o HTML com frequência e
têm proteção anti-bot, o que tornaria o bot frágil. Usar os agregadores é
mais robusto e já cobre o objetivo.

Existe também uma página web (`frontend/`) que mostra os achadinhos
coletados, com busca e filtros — puxa da mesma API (`GET /api/deals`), então
mostra sempre o que o bot também está postando no Telegram. Há ainda um
endpoint separado de comparação de preços em tempo real no Mercado Livre
(`GET /api/search`), que a página não usa.

## Setup rápido

### 1. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` e preencha pelo menos:

```
TELEGRAM_BOT_TOKEN=<token do @BotFather>
TELEGRAM_CHANNEL_ID=@seucanal   # ou -100xxxxxxxxxx se o canal for privado
```

**Como conseguir o token e o canal:**
1. Fale com **@BotFather** no Telegram → `/newbot` → siga as instruções → copie o token.
2. Crie um canal no Telegram e adicione o bot como **administrador** (com permissão de postar).
3. Se o canal for público, use `@nomedocanal` como `TELEGRAM_CHANNEL_ID`.
   Se for privado, encaminhe uma mensagem do canal pro **@JsonDumpBot** pra
   descobrir o `chat_id` numérico (algo como `-1001234567890`).

### 2. Subir a infraestrutura (Postgres + Redis), a API e o bot

```bash
docker compose up -d --build
```

Isso sobe: Postgres (porta 5432), Redis (porta 6379), a API (porta **8010**
no host — a 8000 já estava ocupada por outro projeto nesta máquina, então o
mapeamento externo foi mudado; dentro do container continua sendo 8000) e o
bot (`achadinhos-bot`), já configurados para conversar entre si.

Acompanhar os logs do bot:

```bash
docker compose logs -f bot
```

> Se você não tiver mais nada usando a porta 8000, pode voltar o mapeamento
> pra `"8000:8000"` no `docker-compose.yml` — só lembre de atualizar
> `NEXT_PUBLIC_API_URL` no `frontend/.env.local` também.

### 3. Rodar a página web (frontend)

```bash
cd frontend
npm install   # se ainda não rodou
npm run dev
```

Abre em `http://localhost:3000`. Ela busca os achadinhos na API
(`NEXT_PUBLIC_API_URL`, configurado em `frontend/.env.local` — já aponta pra
`http://localhost:8010` por padrão).

**Atenção:** os scripts `dev`/`build` usam `next dev --webpack` /
`next build --webpack` de propósito. O bundler padrão do Next 16
(Turbopack) trava com um erro de codificação por causa dos acentos no
caminho da pasta (`Transferências`/`programação`) — é um bug do Turbopack,
não do projeto. Se um dia mover o projeto pra um caminho sem acento, pode
tirar o `--webpack` dos scripts.

### 4. Rodar o bot localmente sem Docker (alternativa)

```bash
cd backend
source venv/bin/activate       # já existe um venv pronto no projeto
pip install -r requirements.txt
python -m bot.main_bot
```

Nesse caso, garanta que `DATABASE_URL` e `REDIS_URL` no `.env` apontem para
`localhost` (é o valor padrão) e que Postgres/Redis estejam rodando em algum
lugar acessível (ex: `docker compose up -d postgres redis`).

## Configurações importantes (`.env`)

| Variável | Efeito |
|---|---|
| `DEAL_CHECK_INTERVAL_MINUTES` | Intervalo entre coletas (padrão: 5 min) |
| `DEAL_MIN_DISCOUNT_PCT` | Desconto mínimo (%) pra postar (padrão: 15%). Ofertas sem desconto detectado passam mesmo assim — a ideia é "barato OU com desconto" |
| `DEAL_DEDUP_TTL_DAYS` | Por quantos dias uma URL já postada é considerada duplicata (padrão: 7) |
| `TELEGRAM_POST_COOLDOWN_SECONDS` | Espera entre posts consecutivos pra não tomar rate limit do Telegram (padrão: 120s) |

## Limitações conhecidas

- **Link de compra do Promobit**: aponta pra página da oferta no próprio
  Promobit (não pro link direto da loja), porque o redirecionamento real é
  feito via JavaScript no clique deles — não é exposto no HTML estático. O
  Pelando, por outro lado, já retorna o link direto da loja.
- **Sem link de afiliado próprio**: os campos `affiliate_url` existem no
  modelo mas não são preenchidos — hoje o bot só linka direto pro produto.
  Se quiser monetizar, dá pra plugar um serviço de cloaking de afiliado
  depois (ex: Awin, Lomadee, Amazon Associates) preenchendo esse campo antes
  de publicar.
- **Scraping por HTML**: os dois scrapers (`scrapers/pelando_scraper.py` e
  `scrapers/promobit_scraper.py`) leem estrutura de dados que os próprios
  sites embutem no HTML (não é regex frágil em texto visível). Ainda assim,
  se o Pelando ou o Promobit mudarem a estrutura do site, o scraper
  correspondente pode parar de funcionar — os logs vão indicar isso
  claramente (`Feed vazio`, `bloco de dados não encontrado`, etc.).
- **Sem WhatsApp**: só Telegram por enquanto (WhatsApp exigiria uma lib não
  oficial tipo Baileys, com risco de banimento do número).

## Estrutura do projeto

```
achadinhos/
├── docker-compose.yml       # Postgres + Redis + API + Bot
├── .env.example
├── backend/
│   ├── core/                # config, database, models (SQLAlchemy)
│   ├── bot/                 # pipeline: scheduler, dedup, card, telegram
│   ├── scrapers/            # pelando_scraper, promobit_scraper, mercadolivre
│   └── api/                 # deals (achadinhos) + search (comparação Mercado Livre)
└── frontend/                # página Next.js — lista, busca e filtra os achadinhos
    ├── .env.local            # NEXT_PUBLIC_API_URL
    └── src/
        ├── app/page.tsx       # página principal (busca + grid)
        ├── components/        # DealCard, SearchArea, ui/ (button, input, badge, card)
        └── lib/api.ts          # cliente da API (fetchDeals)
```
