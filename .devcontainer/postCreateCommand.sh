YELO='\033[1;33m'
NC='\033[0m' # No Color

USER=${USER:-"vscode"}
# Codespaces doesn't pickup our node config
NVM_DIR=${NVM_DIR:-"/usr/local/share/nvm"}
. $NVM_DIR/nvm.sh

echo -e "${YELO}Fixing permissions for mounts${NC}"
sudo chown -R $USER $HOME/.tox
chmod -R u+wrx $HOME/.tox
# TODO: transition to ghcr.io/
if [ -z "$(grep -q "docker.pkg.github.com/" /home/$USER/.docker/config.json)" ]; then
    docker pull docker.pkg.github.com/wandb/core/local:local-master
    docker tag docker.pkg.github.com/wandb/core/local:local-master wandb/local:latest
else
    echo "${YELO}Couldn't pull from github, this may cause migrations errors${NC}"
    docker pull wandb/local:latest
fi