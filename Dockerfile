FROM python:3.11-slim

# Use Chinese mirrors for faster downloads
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

COPY . .

EXPOSE 8080

# Default: web mode. Override with: docker run vcut python main.py ...
CMD ["uvicorn", "vcut.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
