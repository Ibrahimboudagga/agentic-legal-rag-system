FROM sweb.base.py.x86_64:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        gcc \
        git \
        libffi-dev \
        libssl-dev \
        pkg-config \
        python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN /opt/miniconda3/bin/conda create -n testbed python=3.11 -y

RUN git clone https://github.com/aio-libs/aiohttp.git /testbed

WORKDIR /testbed

RUN git config --global --add safe.directory /testbed

SHELL ["conda", "run", "-n", "testbed", "/bin/bash", "-c"]

RUN git submodule update --init --recursive

RUN pip install --upgrade pip setuptools wheel Cython

RUN pip install --no-cache-dir \
        attrs \
        charset-normalizer \
        multidict \
        yarl \
        async-timeout \
        frozenlist \
        aiosignal \
        aiohappyeyeballs

RUN pip install --no-cache-dir \
        pytest \
        pytest-asyncio \
        pytest-aiohttp \
        pytest-xdist \
        pytest-cov \
        trustme

ENV AIOHTTP_NO_EXTENSIONS=1

RUN pip install --no-cache-dir -e .

CMD ["conda", "run", "-n", "testbed", "python", "-m", "pytest", "-v", "-rA", "tests/test_client_functional.py", "tests/test_payload.py"]
