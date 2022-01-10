#!/usr/bin/env bash

set -e

# Install zsh-autosuggestions and history substring
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
git clone https://github.com/zsh-users/zsh-history-substring-search ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-history-substring-search

sed -i 's/plugins=(git)/plugins=(git docker kubectl zsh-autosuggestions zsh-history-substring-search)/g' ~/.zshrc
