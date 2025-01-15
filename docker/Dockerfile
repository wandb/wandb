FROM alpine:3.19 AS builder

ARG CLI_VERSION

RUN apk add --no-cache curl tar && \
  ARCH=$(case $(uname -m) in \
  "x86_64") echo "x86_64" ;; \
  "aarch64") echo "arm64" ;; \
  *) echo "x86_64" ;; \
  esac) && \
  curl -L --fail "https://github.com/ctrlplanedev/cli/releases/download/${CLI_VERSION}/ctrlc_Linux_${ARCH}.tar.gz" -o ctrlc.tar.gz && \
  tar xzf ctrlc.tar.gz && \
  mv ctrlc /usr/local/bin/ && \
  chmod +x /usr/local/bin/ctrlc

FROM alpine:3.19 AS final

COPY --from=builder /usr/local/bin/ctrlc /usr/local/bin/ctrlc

ENTRYPOINT ["/usr/local/bin/ctrlc"]
CMD ["--help"]