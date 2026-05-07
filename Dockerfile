FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app.py .
COPY frontend.py .
COPY alembic.ini .
COPY migrations/ ./migrations/
COPY tests/ ./tests/
EXPOSE 8080 3000
CMD ["sh", "-c", "if [ \"$APP_MODE\" = 'frontend' ]; then python frontend.py; else python app.py; fi"]
