# Use uma imagem base do Python
FROM python:3.13-slim

# 1. Instale o Ghostscript usando apt-get (agora funciona dentro do Docker)
RUN apt-get update -o Debug::pkgProblemResolver=yes 2>&1 | grep -v "NO_PUBKEY" && \
apt-get install -y --no-install-recommends ghostscript && \
rm -rf /var/lib/apt/lists/*

# 2. Configure o diretório de trabalho dentro do container
WORKDIR /app

# 3. Copie os arquivos de requisitos e instale as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copie todo o resto do código do seu projeto
COPY . .

# 5. Comando para iniciar a aplicação com Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]