VERSION ?= $(shell git describe --tags --always --dirty)
COMMIT ?= $(shell git rev-parse HEAD)
DATE ?= $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
LDFLAGS = -X github.com/ctrlplanedev/cli/cmd/ctrlc/root/version.Version=$(VERSION) \
          -X github.com/ctrlplanedev/cli/cmd/ctrlc/root/version.GitCommit=$(COMMIT) \
          -X github.com/ctrlplanedev/cli/cmd/ctrlc/root/version.BuildDate=$(DATE)

.PHONY: build
build:
	go build -ldflags "$(LDFLAGS)" -o bin/ctrlc ./cmd/ctrlc

.PHONY: install
install:
	go install -ldflags "$(LDFLAGS)" ./cmd/ctrlc

.PHONY: test
test:
	go test -v ./...

.PHONY: clean
clean:
	rm -rf bin/