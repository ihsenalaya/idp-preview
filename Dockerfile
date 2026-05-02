FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app.py .
COPY alembic.ini .
COPY migrations/ ./migrations/
COPY tests/ ./tests/
EXPOSE 80
CMD ["python", "app.py"]
