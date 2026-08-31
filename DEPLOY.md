# Deploy gratuito / baixo custo do Achadinhos

## Opção mais simples: Render

O Render fornece uma URL gratuita `*.onrender.com` com HTTPS automático e faz deploy a cada push no GitHub.

> Limitação: o Web Service gratuito entra em sleep após inatividade, então não é ideal para um bot que precisa executar 24/7 sem tráfego HTTP.

### API

- Root Directory: `backend`
- Runtime: Docker
- Health Check: `/health`
- Variáveis obrigatórias: `DATABASE_URL`, `REDIS_URL`, `PUBLIC_BASE_URL`
- Para produção, defina `PUBLIC_BASE_URL` como a URL `https://<nome>.onrender.com`

### Banco de dados

Para evitar depender de banco efêmero, use um PostgreSQL externo persistente. Uma opção gratuita para projeto pequeno é Supabase.

### Redis

Use Upstash Redis e copie a URL TLS para `REDIS_URL`.

## Opção 24/7: Oracle Cloud Always Free

Para o bot rodar continuamente, uma VM Always Free é mais apropriada que um serviço que dorme.

Fluxo recomendado:

1. Criar VM Ubuntu Always Free.
2. Instalar Docker e Docker Compose.
3. Clonar `vicksa/achadinhos`.
4. Criar `.env` com as credenciais.
5. Rodar `docker compose up -d`.
6. Usar Caddy/Nginx para HTTPS, ou Cloudflare Tunnel se possuir domínio.

A VM pode ser acessada inicialmente pelo IP público; não é obrigatório comprar domínio para testar.

## Segurança

Nunca faça commit de `.env`, tokens, senhas ou secrets. Use somente variáveis de ambiente no provedor.
