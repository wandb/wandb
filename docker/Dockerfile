FROM alpine:3.19

ARG CLI_VERSION

RUN apk add --no-cache curl tar && \
  curl -L --fail "https://github.com/ctrlplanedev/cli/releases/download/${CLI_VERSION}/ctrlc_Linux_x86_64.tar.gz" -o ctrlc.tar.gz && \
  tar xzf ctrlc.tar.gz && \
  mv ctrlc /usr/local/bin/ && \
  chmod +x /usr/local/bin/ctrlc && \
  rm -rf ctrlc.tar.gz

WORKDIR /app

CMD ["ctrlc", "--help"]