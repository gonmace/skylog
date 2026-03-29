FROM alpine:3.22 AS python-builder
RUN apk add --no-cache python3 py3-pip

FROM n8nio/n8n:latest
USER root
COPY --from=python-builder /usr/bin/python3.12    /usr/bin/python3
COPY --from=python-builder /usr/lib/python3.12    /usr/lib/python3.12
COPY --from=python-builder /usr/lib/libpython3.12.so.1.0 /usr/lib/libpython3.12.so.1.0
RUN ln -sf /usr/lib/libpython3.12.so.1.0 /usr/lib/libpython3.12.so
USER node
