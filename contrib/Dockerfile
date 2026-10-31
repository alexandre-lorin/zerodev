# Image « zero dans un conteneur » : isole le dépôt lancé (voir docs/CONTAINER.md). NON CONSTRUITE par l'auteur (pas de Docker disponible).
#   docker build -f contrib/Dockerfile -t zerodev:latest .
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates build-essential pkg-config libssl-dev \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 zero
RUN install -d -o zero -g zero /home/zero/.zero
COPY . /opt/zerodev
RUN pip install --no-cache-dir /opt/zerodev
USER zero
ENV HOME=/home/zero ZERO_HOME=/home/zero/.zero
WORKDIR /work
ENTRYPOINT ["zero"]
