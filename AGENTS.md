# AGENTS.md

Context file for AI agents working on wandb.

## Project Overview

wandb is a Go project using Python (pip/setuptools).

**Key Info:**
- **Primary Language:** Go
- **Build System:** Python (pip/setuptools)
- **Test Framework:** JUnit, pytest
- **Total Files:** 7477
- **Test Files:** 649
- **AI Readiness Score:** 91/100 (Agent-Optimized)

## Prerequisites

- **Go:** 3.9+ (or applicable language version)
- **Package Manager:** pip or uv (recommended)
- **Test Runner:** JUnit, pytest

## Project Structure

```
wandb/
├── pyproject.toml
├── Cargo.toml
├── Cargo.toml
├── src/                  # Source code
├── tests/                # Test suite (649 files)
└── README.md             # Project documentation
```

## Architecture Overview

### Key Components
- **Main Entry:** main.rs, main.go, main.go, main.go, main.go
- **Test Suite:** 649 test files
- **Build Configuration:** pyproject.toml, Cargo.toml, Cargo.toml

### Design Principles

1. **Modularity** - Code organized by functionality with clear separation of concerns
2. **Testability** - Comprehensive test coverage across critical paths
3. **Clarity** - Explicit naming and structure for AI agent understanding
4. **Consistency** - Uniform patterns and conventions throughout codebase
5. **Maintainability** - Well-documented code with clear intent

## Repository Gotchas (Common Pitfalls)

- **Async Code Without Error Handling**: Async functions lack try/except blocks → Unhandled exceptions can crash the process

## Subsystem Ownership

| Subsystem | Files | Language | Owns | Consumes |
|-----------|-------|----------|------|----------|
| `core/` | 6235 | .go | Core domain logic, business ru... | none |

## Testing Patterns

- **Frameworks**: pytest, JUnit
- **Test Files**: 649
- **Structure**: Tests organized in: Wandb.Tests, analyticstest, apitest, filestreamtest, filetransfertest, httplayerstest, observabilitytest, run-tests, runfilestest, runupsertertest, runworktest, schedulertest, standalone_tests, streamtest, system_tests, test_agent, test_analytics, test_api, test_artifacts, test_automations, test_builder, test_cli, test_core, test_environment, test_experimental, test_file, test_filters, test_functional, test_inputs, test_jupyter_server, test_launch, test_lib, test_media, test_notebooks, test_project, test_public_api, test_registries, test_registry, test_runner, test_sandbox, test_sweep, test_system_metrics, test_tensorboard, test_util, test_wandb_agent, tests, transactionlogtest, unit_tests, watchertest
- **Coverage Tools**: Yes


## Development Workflow

### Initial Setup

```bash
git clone https://github.com/<owner>/wandb.git
cd wandb
pip install -e .              # Install in development mode
# or
uv sync --all-groups          # Using uv (recommended)
```

### Development Commands

#### Running Tests
```bash
pytest                        # Run all tests
pytest tests/                 # Run specific test directory
pytest -v                     # Verbose output with test names
pytest -x                     # Stop on first failure
pytest --cov                  # With coverage report
```

#### Code Quality
```bash
ruff check .                  # Lint with ruff
ruff format .                 # Format code
mypy .                        # Type checking (if configured)
```

## Code Style & Conventions

- **Naming:** Use Go conventions (snake_case for functions, PascalCase for classes)
- **Type Hints:** Yes (strongly encouraged)
- **Error Handling:** Yes
- **Logging:** Yes
- **Testing:** Yes - write tests alongside code changes

## Testing Strategy

**Framework:** JUnit, pytest
**Test Files:** 649 found

Before committing:
1. Run the full test suite: `pytest`
2. Ensure all tests pass
3. Check type hints: `mypy .`
4. Format code: `ruff format .`

## Common Patterns

When contributing to this project:
1. Read existing code in the area you're modifying
2. Follow the established patterns and style
3. Write tests for new functionality
4. Use clear, descriptive variable and function names
5. Add docstrings for public APIs
6. Update tests when changing behavior

## What We Value

✅ Well-tested code with clear intent
✅ Consistent code style and naming conventions
✅ Code that is easy for AI agents to understand
✅ Clear, descriptive commit messages
✅ Modular, reusable components
✅ Comprehensive documentation

## What We Avoid

❌ Large functions doing multiple things
❌ Commented-out dead code
❌ Inconsistent naming or patterns
❌ Unclear error messages
❌ Unexplained magic numbers or strings
❌ Skipped tests or test TODOs

## AI Readiness Dimensions (Scoring)

This project is evaluated across 8 dimensions:

1. **Architecture** (20/100) - Code organization and modularity
2. **Testing** (15/100) - Test coverage and quality
3. **Dependencies** (12/100) - Dependency management
4. **Conventions** (6/100) - Consistent patterns
5. **Entry Points** (10/100) - Clear main/start locations
6. **Security** (10/100) - Input validation and error handling
7. **Build** (10/100) - Clear build/setup instructions
8. **Documentation** (8/100) - Code and project documentation

## Next Steps

Before making changes:
1. Read relevant source files to understand the existing code
2. Look at existing tests for similar functionality
3. Follow the patterns you see in the codebase
4. Write tests for your changes
5. Run `pytest` to verify nothing breaks
6. Run code quality checks: `ruff check . && mypy .`
7. Format your code: `ruff format .`

---

*Generated by Braxis - keeping AI agents in sync with your code*
