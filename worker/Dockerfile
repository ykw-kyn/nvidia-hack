FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker code
COPY recon_worker.py .

ENTRYPOINT ["python3", "/app/recon_worker.py"]