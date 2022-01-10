YELO='\033[1;33m'
NC='\033[0m' # No Color

USER=${USER:-"vscode"}
DEFAULT_PYTHON=${DEFAULT_PYTHON:-"py39"}
# The script is run as root so we need to source nvm, pyenv, and conda
NVM_DIR=${NVM_DIR:-"/usr/local/share/nvm"}
. $NVM_DIR/nvm.sh
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

__conda_setup="$('/opt/conda/bin/conda' 'shell.bash' 'hook' 2> /dev/null)"
if [ $? -eq 0 ]; then
    eval "$__conda_setup"
else
    if [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
        . "/opt/conda/etc/profile.d/conda.sh"
    else
        export PATH="/opt/conda/bin:$PATH"
    fi
fi
unset __conda_setup
conda activate $DEFAULT_PYTHON

echo -e "${YELO}Installing dev dependencies ${NC}"
cd /workspaces/client/
pip install -e .

echo -e "${YELO}Setting up default tox environment ${NC}"
tox --verbose -e $DEFAULT_PYTHON -- tests/test-lib.py

if [ ! -d /var/lib/docker/volumes/wandb-dev ]; then
    echo -e "${YELO}Pulling pre-populated DB ${NC}"
    docker volume create wandb-dev
    wget "https://storage.googleapis.com/wandb/wandb-dev.tar.gz" -O /tmp/wandb-dev.tar.gz
    cd /
    sudo tar -xzf /tmp/wandb-dev.tar.gz
fi