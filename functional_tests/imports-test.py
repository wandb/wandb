"""
check-ext-wandb: {}
assert:
  - :wandb:runs[0][exitcode]: 0
"""

import keras
import pytorch_lightning
import transformers
import spacy
import fastai
import yolov5
import ignite
import catalyst
import skorch
import TTS
import espnet
import catboost
import lightgbm
import sklearn
import xgboost
import detectron2
import detectron
import simpletransformers
import pycaret
import dalle_pytorch
import torch_points3d
import mmdet
import mmcv
import fairseq
import flair
import allennlp
import autogluon
import ray
import autokeras
import avalanche
import hivemind
import optuna
import easyocr
import spleeter
import paddle
import torch_geometric
import horovod
import nni
import syft
import tensorlayer
import deeppavlov
import onmt
import deepctr
import TensorLayer
import tensortrade
import tianshou
import tensorforce
import parl
import stable_baselines3
import deepchem
import icevision
import datasets
import tokenizers
import huggingface_hub
import flash_lightning
import tf_agents
import mmf
import detr
import pytorchvideo
import greykite
import prophet
import parlai
import nemo_toolkit

import wandb

wandb.init()
wandb.finish()
