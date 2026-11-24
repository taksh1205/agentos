# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
ARG INSTALL_EXTRAS=postgres
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Locked dependency set first so source edits do not invalidate the slow layer.
COPY backend/requirements-lock.txt backend/neural-constraints.txt ./
# Optional extra CA for TLS-intercepting corporate proxies (no-op when not supplied):
#   docker build --secret id=extra_ca,src=/path/to/ca.pem ...
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install -r requirements-lock.txt
# The neural profile needs PyTorch. Use the CPU wheel: the default PyPI wheel bundles
# several GB of CUDA libraries that a CPU container never loads.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    case ",${INSTALL_EXTRAS}," in *,ml,*) \
        pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu ;; esac

COPY backend/pyproject.toml ./
COPY backend/agentos ./agentos
COPY evals /evals
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-deps . \
 && pip install ".[${INSTALL_EXTRAS}]" -c neural-constraints.txt \
 && pip check

RUN useradd -m agentos && mkdir /data && chown -R agentos /data /evals
USER agentos
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=30 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "agentos.api:app", "--host", "0.0.0.0", "--port", "8000"]
