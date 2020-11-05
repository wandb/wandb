import pandas as pd
import numpy as np
import wandb
from sklearn.metrics import confusion_matrix
wandb.init(entity='kylegoyette', project="tweets-test-2")

# Get a pandas DataFrame object of all the data in the csv file:
df = pd.read_csv('tweets.csv')

# Get pandas Series object of the "tweet text" column:
text = df['tweet_text']

# Get pandas Series object of the "emotion" column:
target = df['is_there_an_emotion_directed_at_a_brand_or_product']

# Remove the blank rows from the series:
target = target[pd.notnull(text)]
text = text[pd.notnull(text)]

# Perform feature extraction:
from sklearn.feature_extraction.text import CountVectorizer
count_vect = CountVectorizer()
count_vect.fit(text)
counts = count_vect.transform(text)

counts_train = counts[:6000]
target_train = target[:6000]
counts_test = counts[6000:]
target_test = target[6000:]

# Train with this data with a Naive Bayes classifier:
from sklearn.naive_bayes import MultinomialNB

nb = MultinomialNB()
nb.fit(counts, target)

X_test = counts_test
y_test = target_test
y_probas = nb.predict_proba(X_test)
y_pred = nb.predict(X_test)

print("y", y_probas.shape)

# ROC
wandb.log({'roc': wandb.plot.roc_curve(y_test, y_probas, nb.classes_)})

# Precision Recall
wandb.log({'pr': wandb.plot.pr_curve(y_test, y_probas, nb.classes_)})

# Confusion Matrix
class_ind_map = {}
for i, class_name in enumerate(nb.classes_):
    class_ind_map[class_name] = i
y_pred_inds = [class_ind_map[class_name] for class_name in y_pred]
y_true_inds = [class_ind_map[class_name] for class_name in y_test]

wandb.log({'conf_mat': wandb.plot.confusion_matrix(y_pred_inds, y_true_inds, nb.classes_)})
