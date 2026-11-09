FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
COPY fixtures ./fixtures
RUN pip install --no-cache-dir '.[live]' && useradd --create-home --uid 10001 agent && mkdir /app/data && chown agent:agent /app/data
USER agent
EXPOSE 8000
CMD ["uvicorn", "incident_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
