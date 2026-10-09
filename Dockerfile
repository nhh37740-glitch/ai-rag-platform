FROM python:3.11-slim AS prepared

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/agent

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime.txt requirements-build.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt -r requirements-build.txt

COPY specifications/ specifications/
COPY modules-src/ modules-src/
COPY artifacts/ artifacts/
COPY apps/ apps/
COPY skills/ skills/
COPY scripts/ scripts/
COPY data/kb/cmrc2018-demo/ data/kb/cmrc2018-demo/
COPY data/kb/README.md data/kb/README.md
COPY data/kb/user-notebooks/README.md data/kb/user-notebooks/README.md
COPY data/agent-files/README.md data/agent-files/README.md
COPY registry.json pytest.ini ./

# Editable installs are used only to run module tests in the disposable build stage.
RUN pip install --no-cache-dir --no-deps -e specifications \
    && for module in modules-src/*; do \
         if [ -f "$module/pyproject.toml" ]; then \
           pip install --no-cache-dir --no-deps -e "$module"; \
         fi; \
       done
RUN mkdir -p reports

FROM prepared AS source-tested
RUN python scripts/check_module_dependencies.py \
    && sh -n scripts/deploy_compose.sh scripts/deploy_public_demo.sh scripts/deploy_admin_workspace.sh scripts/run_ci_check.sh \
    && python scripts/run_tests.py --mode source --group leaf --junitxml=reports/source-leaf.xml \
    && python scripts/run_tests.py --mode source --group facade --junitxml=reports/source-facade.xml \
    && python scripts/run_tests.py --mode source --group scripts --junitxml=reports/source-integration.xml

FROM source-tested AS compiled
RUN python scripts/compile_extension_modules.py \
    && python scripts/package_release_artifacts.py

FROM compiled AS verified
RUN RAG_EMBED=hash python scripts/verify_compiled_runtime.py \
    && python scripts/run_tests.py --mode binary --group leaf --junitxml=reports/binary-leaf.xml \
    && python scripts/run_tests.py --mode binary --group facade --junitxml=reports/binary-facade.xml \
    && python scripts/run_tests.py --mode binary --group scripts --junitxml=reports/binary-integration.xml \
    && python scripts/run_tests.py --mode binary --group specification --junitxml=reports/specification.xml \
    && python scripts/run_tests.py --mode binary --group app --junitxml=reports/app.xml

# The real model gate runs in Jenkins as a fresh container, never a cached layer.
FROM verified AS builder
RUN python scripts/build_release_bundle.py

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/agent

COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && useradd --create-home --uid 10001 agent

COPY --from=builder /opt/agent/specifications/ specifications/
COPY --from=builder /opt/agent/apps/ apps/
COPY --from=builder /opt/agent/skills/ skills/
COPY --from=builder /opt/agent/artifacts/ artifacts/
COPY --from=builder /opt/agent/registry.json registry.json
COPY --from=builder /opt/agent/data/kb/cmrc2018-demo/ data/kb/cmrc2018-demo/

RUN mkdir -p state models/fastembed_cache data/kb/user-notebooks data/agent-files \
    && chown -R agent:agent state models data/kb/user-notebooks data/agent-files
USER agent

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/demo', timeout=4).read()" || exit 1
CMD ["python", "-m", "uvicorn", "--app-dir", "apps/agent-server", "server:app", "--host", "0.0.0.0", "--port", "8000"]
