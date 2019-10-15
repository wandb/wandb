FROM alpine/git:1.0.7

LABEL "com.github.actions.name"="Commit to another repo"
LABEL "com.github.actions.description"="Commit files to another repo"
LABEL "com.github.actions.icon"="git-commit"
LABEL "com.github.actions.color"="black"

LABEL "repository"="https://github.com/wandb/client"
LABEL "homepage"="https://github.com/wandb/client"
LABEL "maintainer"="Chris Van Pelt <vanpelt@wandb.com>"

COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["sh", "/entrypoint.sh"]