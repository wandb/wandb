FROM alpine:3.19 AS builder

ARG CLI_VERSION

RUN apk add --no-cache curl tar && \
  curl -L --fail "https://github.com/ctrlplanedev/cli/releases/download/${CLI_VERSION}/ctrlc_Linux_x86_64.tar.gz" -o ctrlc.tar.gz && \
  tar xzf ctrlc.tar.gz && \
  mv ctrlc /usr/local/bin/ && \
  chmod +x /usr/local/bin/ctrlc

FROM alpine:3.19 AS final

COPY --from=builder /usr/local/bin/ctrlc /usr/local/bin/ctrlc

CMD ["ctrlc", "--help"]
