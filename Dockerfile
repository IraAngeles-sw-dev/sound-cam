# Use an official Python runtime as base
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy your script into the image
COPY crysound_restapi_svc.py /app/
COPY .env /app/

# (Optional) copy requirements.txt if you have dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Ensure permissions
RUN chmod 644 /app/crysound_restapi_svc.py

# Run your script
CMD ["python", "crysound_restapi_svc.py"]


