FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /code

# Copy requirements and install dependencies
COPY requirements.txt /code/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . /code/

# Create a non-root user first (Hugging Face Spaces runs containers as UID 1000)
RUN useradd -m -u 1000 user

# Writable dirs owned by that user. 777 was world-writable: any other process
# in the container could read the database and every uploaded PDF, or replace
# them. 700 gives the app user exactly what it needs and nobody else anything.
RUN mkdir -p /code/data /code/uploads && \
    chown -R user:user /code && \
    chmod -R 700 /code/data /code/uploads

USER user

# Expose the default Hugging Face container port
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/healthz',timeout=4).status==200 else 1)"

# --proxy-headers so the app sees the real scheme/client through the platform
# proxy (needed for Secure cookies, HSTS and rate limiting to behave correctly).
# --forwarded-allow-ips is left to the platform default; set FORWARDED_ALLOW_IPS
# if you front this with your own proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers"]
