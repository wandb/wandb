# vim:ft=make:

# Setup browser launch
define BROWSER_PYSCRIPT
import os, webbrowser, sys
try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url
webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"

setup-clean:
	rm -fr build/
	rm -fr dist/

test-clean: setup-clean
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete
	rm -rf .tox/
	rm -rf .pytest_cache/

clean-build: setup-clean ## remove build artifacts
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test and coverage artifacts
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

build: clean ## builds source and wheel package
	python -m build -n
	ls -l dist

release-test: build ## package and upload test release
	twine upload --repository testpypi dist/*

release: build ## package and upload release
	twine upload dist/*

bumpversion-to-dev:
	tox -e bumpversion -- --to-dev

bumpversion-from-dev:
	tox -e bumpversion -- --from-dev

code-check:
	tox -e isort-check,pyupgrade-check,mypy,flake8-base,flake8-docstrings -p all

proto:
	nox -s proto-python
	nox -s proto-go

isort:
	isort -o wandb -o gql --force-sort-within-sections $(args)

coverage: ## check code coverage quickly with the default Python
	coverage run --source wandb -m pytest
	coverage report -m
	coverage html
	$(BROWSER) htmlcov/index.html
