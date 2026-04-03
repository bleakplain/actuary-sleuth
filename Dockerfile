FROM node:20-alpine AS frontend-build
WORKDIR /app/scripts/web
COPY scripts/web/package*.json ./
RUN npm ci
COPY scripts/web/ .
RUN npm run build

FROM python:3.10-slim
WORKDIR /app/scripts

COPY scripts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ .

COPY --from=frontend-build /app/scripts/web/dist ./web/dist

EXPOSE 8000
CMD ["python", "run_api.py"]
