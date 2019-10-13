# TensorFlow Example

Here are two examples of logging to W&B from a TensorFlow script.

{% tabs %}
{% tab title="Estimator with TensorBoard" %}
This is a complete example of TensorFlow code using an Estimator that trains a model and saves to W&B.

You can find this example on [GitHub](https://github.com/wandb/examples/blob/master/tf-estimator-mnist/mnist.py) and see the results on [W&B](https://app.wandb.ai/l2k2/examples-tf-estimator-mnist/runs/p0ifowcb).

```python
import tensorflow as tf
import numpy as np
import wandb
wandb.init(project="mnist", sync_tensorboard=True)
wandb.config.batch_size = 256

mnist = tf.contrib.learn.datasets.load_dataset("mnist")


def input(dataset):
    return dataset.images, dataset.labels.astype(np.int32)


# Specify feature
feature_columns = [tf.feature_column.numeric_column("x", shape=[28, 28])]

# Build 2 layer DNN classifier
# NOTE: We change the summary logging frequency to be every epoch with save_summary_steps
classifier = tf.estimator.DNNClassifier(
    feature_columns=feature_columns,
    hidden_units=[256, 32],
    optimizer=tf.train.AdamOptimizer(1e-4),
    n_classes=10,
    dropout=0.1,
    config=tf.estimator.RunConfig(
        save_summary_steps=mnist.train.images.shape[0] / wandb.config.batch_size)
)

# Turn on logging
tf.logging.set_verbosity(tf.logging.INFO)

# Define the training inputs
train_input_fn = tf.estimator.inputs.numpy_input_fn(
    x={"x": input(mnist.train)[0]},
    y=input(mnist.train)[1],
    num_epochs=None,
    batch_size=wandb.config.batch_size,
    shuffle=True,
)

# Train the classifier
classifier.train(input_fn=train_input_fn, steps=100000)

# Define the test inputs
test_input_fn = tf.estimator.inputs.numpy_input_fn(
    x={"x": input(mnist.test)[0]},
    y=input(mnist.test)[1],
    num_epochs=1,
    shuffle=False
)

# Evaluate accuracy
accuracy_score = classifier.evaluate(input_fn=test_input_fn)["accuracy"]
print("\nTest Accuracy: {0:f}%\n".format(accuracy_score*100))
```
{% endtab %}

{% tab title="Raw TensorFlow" %}
This is a complete example of TensorFlow code that trains a model and saves to W&B.

You can find this example on [GitHub](https://github.com/wandb/examples/blob/master/tf-cnn-fashion/train.py) and see the results on [W&B](https://app.wandb.ai/wandb/tensorflow-fashion-mnist/runs/b7ruskvv).

```python
from tensorflow.examples.tutorials.mnist import input_data
import tensorflow as tf
import wandb

def main():
    wandb.init()

    # Import Fashion MNIST data
    data = input_data.read_data_sets('data/fashion')

    categories = {
        0:'T-shirt/Top',
        1:'Trouser',
        2:'Pullover',
        3:'Dress',
        4:'Coat',
        5:'Sandal',
        6:'Shirt',
        7:'Sneaker',
        8:'Bag',
        9:'Ankle Boot'}


    flags = tf.app.flags
    flags.DEFINE_string('data_dir', '/tmp/data',
                        'Directory with the mnist data.')
    flags.DEFINE_integer('batch_size', 128, 'Batch size.')
    flags.DEFINE_float('learning_rate', 0.1, 'Learning rate')

    flags.DEFINE_integer('num_steps', 5000,
                         'Num of batches to train.')
    flags.DEFINE_integer('display_step', 100, 'Steps between displaying output.')
    flags.DEFINE_integer('n_hidden_1', 256, '1st layer number of neurons.')
    flags.DEFINE_integer('n_hidden_2', 256, '2nd layer number of neurons.')
    flags.DEFINE_integer('num_input', 784, 'MNIST data input (img shape: 28*28)')
    flags.DEFINE_integer('num_classes', 10, 'MNIST total classes (0-9 digits)')

    FLAGS = flags.FLAGS

    # Import all of the tensorflow flags into wandb
    wandb.config.update(FLAGS)

    mnist = input_data.read_data_sets("/tmp/data/", one_hot=True)

    # tf Graph input
    X = tf.placeholder("float", [None, FLAGS.num_input])
    Y = tf.placeholder("float", [None, FLAGS.num_classes])

    # Store layers weight & bias
    weights = {
        'h1': tf.Variable(tf.random_normal([FLAGS.num_input, FLAGS.n_hidden_1])),
        'h2': tf.Variable(tf.random_normal([FLAGS.n_hidden_1, FLAGS.n_hidden_2])),
        'out': tf.Variable(tf.random_normal([FLAGS.n_hidden_2, FLAGS.num_classes]))
    }
    biases = {
        'b1': tf.Variable(tf.random_normal([FLAGS.n_hidden_1])),
        'b2': tf.Variable(tf.random_normal([FLAGS.n_hidden_2])),
        'out': tf.Variable(tf.random_normal([FLAGS.num_classes]))
    }

    # Create model
    def neural_net(x):
        # Hidden fully connected layer with 256 neurons
        layer_1 = tf.add(tf.matmul(x, weights['h1']), biases['b1'])
        # Hidden fully connected layer with 256 neurons
        layer_2 = tf.add(tf.matmul(layer_1, weights['h2']), biases['b2'])
        # Output fully connected layer with a neuron for each class
        out_layer = tf.matmul(layer_2, weights['out']) + biases['out']
        return out_layer

    # Construct model
    logits = neural_net(X)
    prediction = tf.nn.softmax(logits)

    # Define loss and optimizer
    loss_op = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
        logits=logits, labels=Y))
    optimizer = tf.train.AdamOptimizer(learning_rate=FLAGS.learning_rate)
    train_op = optimizer.minimize(loss_op)

    # Evaluate model
    correct_pred = tf.equal(tf.argmax(prediction, 1), tf.argmax(Y, 1))
    accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

    # Initialize the variables (i.e. assign their default value)
    init = tf.global_variables_initializer()

    # Start training
    with tf.Session() as sess:
        # Run the initializer
        sess.run(init)

        for step in range(1, FLAGS.num_steps+1):
            batch_x, batch_y = mnist.train.next_batch(FLAGS.batch_size)
            # Run optimization op (backprop)
            sess.run(train_op, feed_dict={X: batch_x, Y: batch_y})
            if step % FLAGS.display_step == 0 or step == 1:
                # Calculate batch loss and accuracy
                loss, acc = sess.run([loss_op, accuracy], feed_dict={X: batch_x,
                                                                     Y: batch_y})
                val_loss, val_acc = sess.run([loss_op, accuracy], feed_dict={
                                                        X: mnist.test.images,
                                                        Y: mnist.test.labels})

                print("Step " + str(step) + ", Minibatch Loss= " + \
                      "{:.4f}".format(loss) + ", Training Accuracy= " + \
                      "{:.3f}".format(acc))

                wandb.log({'acc': acc, 'loss':loss,
                           'val_acc': acc, 'val_loss': val_loss})

if __name__ == '__main__':
   main()
```
{% endtab %}
{% endtabs %}



