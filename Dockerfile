FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        pkg-config \
        python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY ai_contract_review/requirements.txt /app/ai_contract_review/requirements.txt
COPY shared/ /app/shared/
COPY agents/ /app/agents/
COPY ingestion/ /app/ingestion/
COPY retrieval/ /app/retrieval/
COPY client_app/ /app/client_app/

RUN pip install --no-cache-dir -r ai_contract_review/requirements.txt

EXPOSE 8080 9002

CMD ["python", "-m", "ai_contract_review.worker"]
