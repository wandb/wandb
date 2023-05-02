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

test-clean:
	setup-clean
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete
	rm -rf .tox/
	rm -rf .pytest_cache/

clean-build: ## remove build artifacts
	setup-clean
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

clean:	## remove all build, test, coverage and Python artifacts
	clean-build 
	clean-pyc
	clean-test 

build: ## builds source and wheel package
	clean 
	python setup.py sdist bdist_wheel
	ls -l dist

release-test: ## package and upload test release
	dist 
	twine upload --repository testpypi dist/*

release: ## package and upload release
	dist
	twine upload dist/*

bumpversion-to-dev:
	tox -e bumpversion -- --to-dev

bumpversion-from-dev:
	tox -e bumpversion -- --from-dev

code-check:
	tox -e isort-check,ruff-check,pyupgrade-check,black-check,mypy,flake8-base,flake8-docstrings -p all

format:
	tox -e black

proto:
	tox -e proto3
	tox -e proto4

isort:
	isort -o wandb -o gql --force-sort-within-sections $(args)

coverage: ## check code coverage quickly with the default Python
	coverage run --source wandb -m pytest
	coverage report -m
	coverage html
	$(BROWSER) htmlcov/index.html
