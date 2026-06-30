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

# Create folders for uploads and data and set permissions for Hugging Face user (uid 1000)
RUN mkdir -p /code/data /code/uploads && \
    chmod -R 777 /code/data /code/uploads

# Create a non-root user (Hugging Face Spaces runs containers with UID 1000)
RUN useradd -m -u 1000 user
RUN chown -R user:user /code
USER user

# Expose the default Hugging Face container port
EXPOSE 7860

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
