# Scikit Example



This is a complete example of scikit code that trains an SVM and saves to W&B.

You can find this example on [GitHub](https://github.com/wandb/examples/blob/master/scikit-iris/train.py) and see the results on [W&B](https://app.wandb.ai/l2k2/iris).

```python
import numpy as np
from sklearn import datasets
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC
import wandb

wandb.init(project="iris", 
           config={"gamma":0.1, "C":1.0, "test_size": 0.3, "seed": 0})

iris = datasets.load_iris()

X = iris.data[:, [2, 3]]
y = iris.target

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=wandb.config.test_size, random_state=wandb.config.seed)

sc = StandardScaler()
sc.fit(X_train)

X_train_std = sc.transform(X_train)
X_test_std = sc.transform(X_test)

X_combined_std = np.vstack((X_train_std, X_test_std))
y_combined = np.hstack((y_train, y_test))

svm = SVC(kernel='rbf', random_state=wandb.config.seed, gamma=wandb.config.gamma, C=wandb.config.C)
svm.fit(X_train_std, y_train)

wandb.log({"Train Accuracy": svm.score(X_train_std, y_train), 
           "Test Accuracy": svm.score(X_test_std, y_test)})

def plot_data():
    from matplotlib.colors import ListedColormap
    import matplotlib.pyplot as plt

    markers = ('s', 'x', 'o')
    colors = ('red', 'blue', 'lightgreen')
    cmap = ListedColormap(colors[:len(np.unique(y_test))])
    for idx, cl in enumerate(np.unique(y)):
        plt.scatter(x=X[y == cl, 0], y=X[y == cl, 1],
               c=cmap(idx), marker=markers[idx], label=cl)

    wandb.log({"Data": plt})

plot_data()
```

