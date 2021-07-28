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


coverage: ## check code coverage quickly with the default Python
	coverage run --source wandb -m pytest
	coverage report -m
	coverage html
	$(BROWSER) htmlcov/index.html


submodule-init: ## check if submodule has been initialized, if not, clone from remote
	if ! git submodule foreach git status | grep sweeps > /dev/null; then \
	git submodule update --init --remote; \
	fi

submodule-update: submodule-init  # checkout the pinned version of submodules
	git submodule update

release-test: dist ## package and upload test release
	twine upload --repository testpypi dist/*

release: dist ## package and upload release
	twine upload dist/*

dist: clean submodule-init ## builds source and wheel package
	python setup.py sdist bdist_wheel
	ls -l dist

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

setup-clean:
	rm -fr build/
	rm -fr dist/

test-clean:
	rm -fr build/
	rm -fr dist/
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete
	rm -rf .tox/
	rm -rf .pytest_cache/

test:
	tox -e "codemod,black,mypy,flake8,flake8-docstrings"

test-full:
	tox

test-short:
	tox -e "codemod,black,mypy,flake8,flake8-docstrings,py36"

format:
	tox -e format

proto:
	tox -e proto

isort:
	isort -o wandb -o gql --force-sort-within-sections $(args)

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test and coverage artifacts
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/

bumpversion-to-dev:
	tox -e bumpversion-to-dev

bumpversion-from-dev:
	tox -e bumpversion-from-dev

