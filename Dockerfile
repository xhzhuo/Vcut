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

ENV VCUT_INPUTS_DIR=/data/inputs
ENV VCUT_OUTPUT_DIR=/data/output
ENV VCUT_ARTIFACTS_DIR=/data/artifacts

# Symlink so pipeline's infer_group_from_source_paths can find /data/inputs as workspace/inputs
RUN ln -sfn /data/inputs inputs && ln -sfn /data/artifacts artifacts

EXPOSE 8080

# Default: web mode. Override with: docker run vcut python main.py ...
# Mount volumes: -v /path/to/inputs:/data/inputs -v /path/to/artifacts:/data/artifacts -v /path/to/output:/data/output
CMD ["uvicorn", "vcut.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
