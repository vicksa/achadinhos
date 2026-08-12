FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema para Playwright e Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar o Chromium do Playwright (usado pelo bot/twitter_publisher.py)
RUN playwright install --with-deps chromium

# Copiar o código fonte
COPY . .

# Porta padrão do FastAPI
EXPOSE 8000

# Comando padrão (sobrescrito no docker-compose por serviço)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
