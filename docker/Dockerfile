FROM golang:1.24-alpine AS builder

WORKDIR /app

COPY . .

RUN go build -o /usr/local/bin/ctrlc ./cmd/ctrlc && \
  chmod +x /usr/local/bin/ctrlc

FROM alpine:3.19 AS final

COPY --from=builder /usr/local/bin/ctrlc /usr/local/bin/ctrlc

ENTRYPOINT ["/usr/local/bin/ctrlc"]
CMD ["--help"]