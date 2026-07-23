# Stage 1: build the MapLibre frontend
FROM node:22-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python app; serves API + built frontend on one port
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ api/
COPY ingest/ ingest/
COPY extract/ extract/
COPY sim/ sim/
COPY scripts/ scripts/
COPY db/ db/
COPY --from=webbuild /web/dist web/dist
ENV PORT=8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
