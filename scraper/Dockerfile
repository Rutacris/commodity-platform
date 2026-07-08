FROM python:3.11-slim

WORKDIR /app

# System deps for pdfplumber (needs poppler) and lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data and logs directories
RUN mkdir -p data logs

# Default: run all scrapers then exit (designed for cron / docker start)
CMD ["python", "main.py"]
