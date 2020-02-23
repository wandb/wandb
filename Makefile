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
