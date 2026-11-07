FROM python:3.12-slim-bookworm

# amulet-leveldb / amulet-nbt ship mac+windows wheels only. Linux must compile
# the Cython/C++ extensions. Python 3.12 has working numpy 1.26 wheels.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CACHE_DIR=/opt/amulet-cache \
    MCREAD_TMP=/tmp/mcread \
    HOST=0.0.0.0 \
    PORT=8080 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        zlib1g-dev \
        libzstd-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
        "setuptools>=70" \
        wheel \
        "cython>=3.0.11" \
        versioneer \
    && pip install --no-cache-dir --no-build-isolation -r requirements.txt \
    && python -c "from minecraft_model_reader.api.resource_pack.java import download_resources as d; d.get_java_vanilla_latest()"

COPY mcread mcread
COPY tools tools
COPY viewer viewer

RUN mkdir -p /tmp/mcread viewer/generated \
    && chmod -R a+rwX /tmp/mcread viewer/generated /opt/amulet-cache

EXPOSE 8080

CMD ["sh", "-c", "python tools/serve_viewer.py --host 0.0.0.0 --port ${PORT:-8080}"]
