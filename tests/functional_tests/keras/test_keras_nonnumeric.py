import pandas as pd
import tensorflow as tf
import wandb

dftrain = pd.read_csv("https://storage.googleapis.com/tf-datasets/titanic/train.csv")
y_train = dftrain.pop("survived")
dftrain = dftrain[["sex", "class", "age", "fare", "n_siblings_spouses", "parch"]]
STRING_CATEGORICAL_COLUMNS = [
    "sex",
    "class",
]
INT_CATEGORICAL_COLUMNS = ["n_siblings_spouses", "parch"]
NUMERIC_COLUMNS = ["age", "fare"]
wandb.init(project="keras-experimental")
keras_inputs = {}
keras_preproc_inputs = []
for key in STRING_CATEGORICAL_COLUMNS:
    keras_input = tf.keras.Input(shape=(1,), dtype=tf.string, name=key)
    keras_inputs[key] = keras_input
    vocab = dftrain[key].unique()
    keras_preproc_input = tf.keras.layers.experimental.preprocessing.StringLookup(
        output_mode="int", name="lookup" + key, vocabulary=vocab
    )(keras_input)
    # random_weights = [random.uniform(0, 1) for _ in range(len(vocab))]
    # keras_preproc_input.set_vocabulary(vocabulary=vocab, idf_weights=random_weights)
    # keras_preproc_input = keras_preproc_input(keras_input)
    keras_preproc_inputs.append(keras_preproc_input)

for key in INT_CATEGORICAL_COLUMNS:
    keras_input = tf.keras.Input(shape=(1,), dtype=tf.int64, name=key)
    keras_inputs[key] = keras_input
    vocab = dftrain[key].unique()
    keras_preproc_input = tf.keras.layers.experimental.preprocessing.IntegerLookup(
        vocabulary=vocab, num_oov_indices=0, mask_value=None, name="lookup" + key
    )(keras_input)
    keras_preproc_input = tf.keras.layers.experimental.preprocessing.CategoryEncoding(
        num_tokens=len(vocab), output_mode="count", sparse=True, name="encode" + key
    )(keras_preproc_input)
    keras_preproc_inputs.append(keras_preproc_input)

for key in NUMERIC_COLUMNS:
    keras_input = tf.keras.Input(shape=(1,), dtype=tf.float32, name=key)
    keras_inputs[key] = keras_input
    keras_preproc_inputs.append(keras_preproc_input)

age_x_sex = tf.keras.layers.experimental.preprocessing.CategoryCrossing(
    name="age_x_sex_crossing"
)([keras_inputs["age"], keras_inputs["sex"]])
age_x_sex = tf.keras.layers.experimental.preprocessing.Hashing(
    num_bins=100, name="age_x_sex_hashing"
)(age_x_sex)
keras_output_age_x_sex = tf.keras.layers.experimental.preprocessing.CategoryEncoding(
    num_tokens=100, output_mode="count", sparse=True, name="age_x_sex_encoding"
)(age_x_sex)
keras_preproc_inputs.append(keras_output_age_x_sex)


linear_model = tf.keras.experimental.LinearModel(
    units=5, kernel_initializer="zeros", activation="sigmoid"
)
linear_model2 = tf.keras.experimental.LinearModel(
    units=1, kernel_initializer="zeros", activation="sigmoid"
)
linear_logits1 = linear_model(keras_preproc_inputs)
linear_logits2 = linear_model2(linear_logits1)
sorted_keras_inputs = tuple(keras_inputs[key] for key in sorted(keras_inputs.keys()))
model = tf.keras.Model(sorted_keras_inputs, linear_logits2)

model.compile("ftrl", "binary_crossentropy", metrics=["accuracy"])

df_dataset = tf.data.Dataset.from_tensor_slices((dict(dftrain), y_train))


def encode_map(features, labels):
    encoded_features = tuple(
        tf.expand_dims(features[key], axis=1) for key in sorted(features.keys())
    )
    return (encoded_features, labels)


encoded_dataset = df_dataset.batch(32).map(encode_map)

z = model.weights
model.fit(
    encoded_dataset,
    callbacks=[
        wandb.keras.WandbCallback(
            log_weights=True, log_gradients=True, training_data=encoded_dataset
        )
    ],
    epochs=10,
)
