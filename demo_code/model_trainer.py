
# Verify the you installed this branch with
# pip install -e ../ -U 
import wandb
from wandb.lab.workflows import log_model, link_model
from UserCode import *
import os

os.environ['WANDB_BASE_URL'] = 'http://api.wandb.test'

project = "model_reg_example_trainer_3"

run = wandb.init(config={
    "batch_size"    : 64,
    "gamma"         : 0.7,
    "lr"            : 1.0,
    "epochs"        : 3,
    "seed"          : 1,
    "train_count"   : 500,
    "val_count"     : 10,
    "link_model_name"    : "SKO 2" # change me to a value after manually making a registry
}, project=project)

cfg                     = wandb.config
_                       = seed(cfg.seed)

train_data, val_data    = load_training_data_split(train_count=cfg.train_count, val_count=cfg.val_count)
model, opt              = build_model(lr=cfg.lr)

lowest_loss             = math.inf
best_model              = None

def onEpochEnd(epoch, model):
    global lowest_loss
    global best_model

    val_loss, val_acc, _ = evaluate_model(model, val_data)
    
    wandb.log({
        "epoch"    : epoch, 
        "val_loss" : val_loss, 
        "val_acc"  : val_acc
    })
    
    if val_loss < lowest_loss:
        lowest_loss     = val_loss
        best_model      = log_model(model, "mnist_nn", aliases=["best"])
    else:
        _               = log_model(model, "mnist_nn")
    

_ = train_model(
    model        = model, 
    optimizer    = opt, 
    train_data   = train_data, 
    batch_size   = cfg.batch_size, 
    gamma        = cfg.gamma, 
    epochs       = cfg.epochs, 
    onEpochEnd   = onEpochEnd
)

if cfg["link_model_name"] and cfg["link_model_name"] != "":
    link_model(best_model, cfg["link_model_name"])
