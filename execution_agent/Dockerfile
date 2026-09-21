FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
COPY execution_agent/requirements.txt execution_agent-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r execution_agent-requirements.txt

COPY . .

CMD ["python", "-m", "execution_agent.runner"]
