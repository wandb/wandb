# vim:ft=make:

setup-clean:
	rm -fr build/
	rm -fr dist/

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

build-alpha: clean ## builds source and wheel package
	WANDB_CORE_ALPHA=true python setup.py sdist bdist_wheel
	ls -l dist

release-alpha-test: build-alpha ## package and upload test release
	twine upload --repository testpypi dist/*

release-alpha: build-alpha ## package and upload test release
	twine upload dist/*
