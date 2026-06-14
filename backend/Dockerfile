FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# Make entrypoint executable
RUN chmod +x /app/start.sh

# SQLite lives on a mounted volume; default path inside container
ENV TAF_DB_PATH=/data/taf_accuracy.db

EXPOSE 8080

CMD ["/app/start.sh"]
