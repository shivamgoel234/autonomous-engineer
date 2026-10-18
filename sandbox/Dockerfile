FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.5 fastapi==0.115.12
COPY runner.py /runner.py
USER 65534:65534
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
ENTRYPOINT ["python", "/runner.py"]
