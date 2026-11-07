FROM python:3.12-slim-bookworm

# Linux has no wheels for amulet-leveldb / amulet-nbt / amulet-mutf8 (mac+win
# only). Cloud Build compiles those Cython/C++ extensions. The last three
# failures were all "next missing native tool" (compiler, numpy, cmake), so
# install a full toolchain up front instead of discovering them one by one.
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
        cmake \
        ninja-build \
        pkg-config \
        git \
        zlib1g-dev \
        libzstd-dev \
        libsnappy-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Python-side build backends + numpy (imported at metadata time). The pypi
# cmake/ninja wheels put `cmake`/`ninja` on PATH even if apt is skipped.
RUN pip install --no-cache-dir \
        "setuptools>=70" \
        wheel \
        "cython>=3.0.11" \
        versioneer \
        "numpy==1.26.4" \
        cmake \
        ninja \
        pybind11 \
        scikit-build \
        scikit-build-core \
    && pip install --no-cache-dir --no-build-isolation -r requirements.txt \
    && python -c "from minecraft_model_reader.api.resource_pack.java import download_resources as d; d.get_java_vanilla_latest()"

COPY mcread mcread
COPY tools tools
COPY viewer viewer

RUN mkdir -p /tmp/mcread viewer/generated \
    && chmod -R a+rwX /tmp/mcread viewer/generated /opt/amulet-cache

EXPOSE 8080

CMD ["sh", "-c", "python tools/serve_viewer.py --host 0.0.0.0 --port ${PORT:-8080}"]
