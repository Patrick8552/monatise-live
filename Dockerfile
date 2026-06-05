FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements-live.txt

ENV MONATISE_PORT=4174
ENV MONATISE_HOST=0.0.0.0
EXPOSE 4174
CMD ["python", "scripts/serve_live.py"]
