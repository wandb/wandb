.PHONY: clean clean-test clean-pyc clean-build docs help
.DEFAULT_GOAL := help
define BROWSER_PYSCRIPT
import os, webbrowser, sys
try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"

ifeq ($(strip $(shell git status --untracked-files=no --porcelain 2>/dev/null)),)
	GIT_TREE_STATE=clean
else
	GIT_TREE_STATE=dirty
endif

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts


clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
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

lint: ## check style with flake8
	flake8 wandb tests

test: ## run tests quickly with the default Python
	py.test	

test-all: ## run tests on every Python version with tox
	CIRCLE_TEST_REPORTS=/tmp tox

coverage: ## check code coverage quickly with the default Python
	coverage run --source wandb -m pytest
	
		coverage report -m
		coverage html
		$(BROWSER) htmlcov/index.html

docs: ## generate Sphinx HTML documentation, including API docs
	rm -f docs/wandb.rst
	rm -f docs/modules.rst
	sphinx-apidoc -o docs/ wandb
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	$(BROWSER) docs/_build/html/index.html

servedocs: docs ## compile the docs watching for changes
	watchmedo shell-command -p '*.rst' -c '$(MAKE) -C docs html' -R -D .

gitdirty:
ifeq ($(GIT_TREE_STATE),dirty)
	$(error un-committed changes, commit before continuing)
endif

release: dist ## package and upload a release
	git push
	twine upload dist/*

release-test: dist ## package and upload test release
	twine upload --repository-url https://test.pypi.org/legacy/ dist/*

dist: clean ## builds source and wheel package
	python setup.py sdist bdist_wheel
	ls -l dist

arena: dist
	cp -r dist wandb/kubeflow
	docker build wandb/kubeflow -t wandb/arena

install: clean ## install the package to the active Python's site-packages
	python setup.py install
