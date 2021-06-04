import wandb
import pickle
import sys
settings = pickle.load(open(sys.argv[1], 'rb'))
wandb.init(settings=settings, anonymous='must')
