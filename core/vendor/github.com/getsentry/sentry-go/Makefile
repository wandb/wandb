.DEFAULT_GOAL := help

ALL_GO_MOD_DIRS := $(shell find . -type f -name 'go.mod' -exec dirname {} \; | sort)
GO = go
TIMEOUT = 300

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
.PHONY: help

build: ## Build all workspace modules
	$(GO) build work
.PHONY: build

test: ## Run tests across all workspace modules
	$(GO) test -count=1 -timeout $(TIMEOUT)s work
.PHONY: test

test-race: ## Run tests with race detection
	$(GO) test -count=1 -timeout $(TIMEOUT)s -race work
.PHONY: test-race

COVERAGE_MODE = atomic
COVERAGE_DIR = .coverage
COVERAGE_PROFILE = $(COVERAGE_DIR)/coverage.out

$(COVERAGE_DIR):
	mkdir -p $(COVERAGE_DIR)

test-coverage: $(COVERAGE_DIR) ## Test with coverage enabled
	rm -f $(COVERAGE_DIR)/*
	$(GO) test -count=1 -timeout $(TIMEOUT)s -covermode=$(COVERAGE_MODE) -coverprofile=$(COVERAGE_PROFILE) work
.PHONY: test-coverage

test-race-coverage: $(COVERAGE_DIR) ## Run tests with race detection and coverage
	rm -f $(COVERAGE_DIR)/*
	$(GO) test -count=1 -timeout $(TIMEOUT)s -race -covermode=$(COVERAGE_MODE) -coverprofile=$(COVERAGE_PROFILE) work
.PHONY: test-race-coverage

vet: ## Run "go vet" across all workspace modules
	$(GO) vet work
.PHONY: vet

mod-tidy: ## Check go.mod tidiness
	@set -e ; \
	for dir in $(ALL_GO_MOD_DIRS); do \
		MOD_GO=$$(sed -n 's/^go \([0-9.]*\)/\1/p' "$${dir}/go.mod"); \
		echo ">>> Running 'go mod tidy' for module: $${dir} (go $${MOD_GO})"; \
		(cd "$${dir}" && GOTOOLCHAIN=local $(GO) mod tidy -go=$${MOD_GO} -compat=$${MOD_GO}); \
	done; \
	git diff --exit-code
.PHONY: mod-tidy

gotidy: $(ALL_GO_MOD_DIRS:%=gotidy/%) ## Run go mod tidy across all modules
gotidy/%: DIR=$*
gotidy/%:
	@echo "==> $(DIR)" && (cd "$(DIR)" && $(GO) mod tidy)
.PHONY: gotidy

lint: ## Lint (using "golangci-lint")
	golangci-lint run
.PHONY: lint

fmt: ## Format all Go files
	gofmt -l -w -s .
.PHONY: fmt
