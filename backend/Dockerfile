FROM python:3.12-slim
WORKDIR /app
ARG INSTALL_EXTRAS=postgres
COPY backend/pyproject.toml ./
COPY backend/agentos ./agentos
COPY evals /evals
RUN pip install --no-cache-dir ".[${INSTALL_EXTRAS}]"
RUN useradd -m agentos && mkdir /data && chown -R agentos /data /evals
USER agentos
EXPOSE 8000
CMD ["uvicorn","agentos.api:app","--host","0.0.0.0","--port","8000"]
