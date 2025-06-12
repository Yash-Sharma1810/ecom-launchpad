# Use an official Python image
FROM python:3.11-slim

# Set up a work directory
WORKDIR /app

# Install system dependencies needed for Chrome and Selenium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    --no-install-recommends

# Install Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get -y update \
    && apt-get install -y google-chrome-stable

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . .

# Expose the port the app runs on
EXPOSE 10000

# Command to run your application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]