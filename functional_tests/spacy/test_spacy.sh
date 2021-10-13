#!/bin/sh
python3 -m spacy project clone integrations/wandb
cd wandb
python3 -m spacy project run install
python3 -m spacy project assets
python3 -m spacy project run log
