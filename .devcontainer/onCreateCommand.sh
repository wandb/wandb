YELO='\033[1;33m'
NC='\033[0m' # No Color

USER=${USER:-"vscode"}
DEFAULT_PYTHON=${DEFAULT_PYTHON:-"py39"}
# The script is run as root so we need to source nvm and pyenv
NVM_DIR=${NVM_DIR:-"/usr/local/share/nvm"}
. $NVM_DIR/nvm.sh
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

echo -e "${YELO}Installing dev dependencies ${NC}"
cd /workspaces/client/
mamba run -n $DEFAULT_PYTHON pip install -e .

echo -e "${YELO}Setting up default tox environment ${NC}"
# TODO: we need to change the workdir in tox.ini
mamba run -n $DEFAULT_PYTHON tox --verbose -e $DEFAULT_PYTHON -- tests/test-lib.py

if [ ! -d /var/lib/docker/volumes/wandb-dev ]; then
    echo -e "${YELO}Pulling pre-populated DB ${NC}"
    docker volume create wandb-dev
    wget "https://storage.googleapis.com/wandb/wandb-dev.tar.gz" -O /tmp/wandb-dev.tar.gz
    cd /
    sudo tar -xzf /tmp/wandb-dev.tar.gz
fi