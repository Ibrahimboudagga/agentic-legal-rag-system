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

COPY app/ai_contract_review/requirements.txt /app/ai_contract_review/requirements.txt
COPY app/shared/ /app/shared/
COPY app/agents/ /app/agents/
COPY app/ingestion/ /app/ingestion/
COPY app/retrieval/ /app/retrieval/
COPY app/tools/ /app/tools/
COPY app/client_app/ /app/client_app/

RUN pip install --no-cache-dir -r ai_contract_review/requirements.txt

EXPOSE 8080 9002

CMD ["python", "-m", "ai_contract_review.worker"]
