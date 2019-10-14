
# wandb.keras
[source](https://github.com/wandb/client/blob/feature/docs/wandb/keras/__init__.py#L0)


## WandbCallback
[source](https://github.com/wandb/client/blob/feature/docs/wandb/keras/__init__.py#L134)
```python
WandbCallback(self,
              monitor='val_loss',
              verbose=0,
              mode='auto',
              save_weights_only=False,
              log_weights=False,
              log_gradients=False,
              save_model=True,
              training_data=None,
              validation_data=None,
              labels=[],
              data_type=None,
              predictions=36,
              generator=None,
              input_type=None,
              output_type=None,
              log_evaluation=False,
              validation_steps=None,
              class_colors=None)
```
WandbCallback automatically integrates keras with wandb.

**Examples**:

```python
model.fit(X_train, y_train,  validation_data=(X_test, y_test),
callbacks=[WandbCallback()])
```
 
 WandbCallback will automatically log history data from any metrics collected by keras: loss and anything passed into keras_model.compile()
 
 WandbCallback will set summary metrics for the run associated with the "best" training step, where "best" is defined by the `monitor` and `mode` attribues.  This defaults to the epoch with the minimum val_loss. WandbCallback will by default save the model associated with the best epoch..
 
 WandbCallback can optionally log gradient and parameter histograms.
 
 WandbCallback can optionally save training and validation data for wandb to visualize.
 

**Arguments**:

- `monitor` _str_ - name of metric to monitor.  Defaults to val_loss.
- `mode` _str_ - one of {"auto", "min", "max"}. "min" - save model when monitor is minimized "max" - save model when monitor is maximized "auto" - try to guess when to save the model (default). save_model: True - save a model when monitor beats all previous epochs False - don't save models
- `save_weights_only` _boolean_ - if True, then only the model's weights will be saved (`model.save_weights(filepath)`), else the full model is saved (`model.save(filepath)`).
- `log_weights` - (boolean) if True save histograms of the model's layer's weights.
- `log_gradients` - (boolean) if True log histograms of the training gradients
- `training_data` - (tuple) Same format (X,y) as passed to model.fit.  This is needed for calculating gradients - this is mandatory if `log_gradients` is `True`.
- `validate_data` - (tuple) Same format (X,y) as passed to model.fit.  A set of data for wandb to visualize.  If this is set, every epoch, wandb will make a small number of predictions and save the results for later visualization.
- `generator` _generator_ - a generator that returns validation data for wandb to visualize.  This generator should return tuples (X,y).  Either validate_data or generator should be set for wandb to visualize specific data examples.
- `validation_steps` _int_ - if `validation_data` is a generator, how many steps to run the generator for the full validation set.
- `labels` _list_ - If you are visualizing your data with wandb this list of labels will convert numeric output to understandable string if you are building a multiclass classifier.  If you are making a binary classifier you can pass in a list of two labels ["label for false", "label for true"].  If validate_data and generator are both false, this won't do anything.
- `predictions` _int_ - the number of predictions to make for visualization each epoch, max is 100.
- `input_type` _string_ - type of the model input to help visualization. can be one of: ("image", "images", "segmentation_mask").
- `output_type` _string_ - type of the model output to help visualziation. can be one of: ("image", "images", "segmentation_mask").
- `log_evaluation` _boolean_ - if True save a dataframe containing the full validation results at the end of training.
- `class_colors` - ([float, float, float]) if the input or output is a segmentation mask, an array containing an rgb tuple (range 0-1) for each class.
 
 
