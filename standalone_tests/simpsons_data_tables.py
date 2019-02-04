#!/usr/bin/env python

"""Trains a classifier for frames from the Simpsons.

Useful for testing data tables.
"""

import math
import os
import subprocess

from keras.models import Sequential
from keras.layers import Conv2D, MaxPooling2D, Dropout, Dense, Flatten
from keras.preprocessing.image import ImageDataGenerator
from keras import optimizers
import numpy as np
import pandas as pd

import wandb
from wandb.keras import WandbCallback

run = wandb.init()
config = run.config
config.img_size = 50
config.batch_size = 256
config.epochs = 0

# download the data if it doesn't exist
if not os.path.exists("simpsons"):
    print("Downloading Simpsons dataset...")
    subprocess.check_output(
        "curl https://storage.googleapis.com/wandb-production.appspot.com/mlclass/simpsons.tar.gz | tar xvz", shell=True)

# this is the augmentation configuration we will use for training
# see: https://keras.io/preprocessing/image/#imagedatagenerator-class
train_datagen = ImageDataGenerator(
    rescale=1./255)

# only rescaling augmentation for testing:
test_datagen = ImageDataGenerator(rescale=1./255)

# this is a generator that will read pictures found in
# subfolers of 'data/train', and indefinitely generate
# batches of augmented image data
train_generator = train_datagen.flow_from_directory(
    'simpsons/train',  # this is the target directory
    target_size=(config.img_size, config.img_size),
    batch_size=config.batch_size)

# this is a similar generator, for validation data
test_generator = test_datagen.flow_from_directory(
    'simpsons/test',
    target_size=(config.img_size, config.img_size),
    batch_size=config.batch_size)

labels = list(test_generator.class_indices.keys())

model = Sequential()
model.add(Conv2D(32, (3, 3), input_shape=(
    config.img_size, config.img_size, 3), activation="relu"))
model.add(MaxPooling2D())
model.add(Flatten())
model.add(Dropout(0.4))
model.add(Dense(50, activation="relu"))
model.add(Dropout(0.4))
model.add(Dense(13, activation="softmax"))
model.compile(optimizer=optimizers.Adam(),
              loss='categorical_crossentropy', metrics=['accuracy'])

model.fit_generator(
    train_generator,
    steps_per_epoch=len(train_generator),
    epochs=config.epochs,
    workers=4,
    validation_data=test_generator,
    validation_steps=len(test_generator))

data_gen = ImageDataGenerator(rescale=1./255)
gen = data_gen.flow_from_directory(
    'simpsons/test',
    target_size=(run.config['img_size'], run.config['img_size']),
    batch_size=run.config['batch_size'], shuffle=False)
class_cols = list(gen.class_indices.keys())
classes = [c.replace('_', ' ') for c in gen.class_indices.keys()]

cards = []
true_class_is = []
true_classes = []
true_probs = []
pred_classes = []
pred_probs = []
class_probs = [[] for c in classes]

for batch_i in range(int(math.ceil(len(gen.filenames) / gen.batch_size))):
    examples, truth = next(gen)
    preds = model.predict(np.stack(examples))

    this_true_class_is = [np.argmax(probs) for probs in truth]
    true_class_is.extend(this_true_class_is)
    true_classes.extend(classes[i] for i in this_true_class_is)
    true_probs.extend(ps[i] for ps, i in zip(preds, true_class_is))
    pred_classes.extend(classes[np.argmax(probs)] for probs in preds)
    pred_probs.extend(np.max(probs) for probs in preds)
    for cp, p in zip(class_probs, preds.T):
        cp.extend(p)

    base_i = batch_i * gen.batch_size

    for i in range(base_i, base_i + len(examples)):
        try:
            cards.append('''```Predicted:  
{pred_class} ({pred_prob:.2%})  
Actual:  
{true_class} ({true_prob:.2%})  
![](https://api.wandb.ai/adrianbg/simpsons/tgw7wnqj/simpsons/{idx}.jpg)
            ```'''.format(true_class=true_classes[i], true_prob=true_probs[i], pred_class=pred_classes[i], pred_prob=pred_probs[i], idx=i))
        except IndexError:
            print(i, idx)
            print(truths.shape)
            print(true_prob.shape)
            import sys
            sys.exit()
    
col_names = ['wandb_example_id', 'card', 'true_class', 'true_prob', 'pred_class', 'pred_prob'] + class_cols
frame_dict = {
    'wandb_example_id': gen.filenames[:len(cards)],
    'card': cards,
    'true_class': true_classes,
    'true_prob': true_probs,
    'pred_class': pred_classes,
    'pred_prob': pred_probs,
}
for c, col in zip(class_cols, class_probs):
    frame_dict[c] = col

table = pd.DataFrame(frame_dict, columns=col_names)

number_cols = ['true_prob', 'pred_prob'] + class_cols
table[number_cols] = table[number_cols].apply(pd.to_numeric)
#from IPython import embed; embed()
    
wandb.run.summary.update({"dataset": table})