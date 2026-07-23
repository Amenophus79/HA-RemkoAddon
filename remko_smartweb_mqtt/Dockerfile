FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION=0.2.8
ARG BUILD_ARCH=amd64

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN \
  apk add --no-cache \
    ca-certificates \
    chromium \
    chromium-chromedriver \
    py3-pip \
    py3-virtualenv \
    python3

WORKDIR /app

COPY requirements.txt /app/
RUN \
  python3 -m virtualenv /opt/venv && \
  /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
  /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY remko_smartweb_mqtt /app/remko_smartweb_mqtt
COPY run.sh /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
