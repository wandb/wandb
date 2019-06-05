from __future__ import absolute_import


run_once = False

def wandb_keras_hooks_install():
    # TODO: Need to safely check if keras is installed
    import wandb
    import keras
    global run_once

    def fit(self, *args, **kwargs):
        callbacks = kwargs.pop("callbacks", [])
        callbacks.append(keras.callbacks.TensorBoard(log_dir=wandb.run.dir))
        callbacks.append(wandb.keras.WandbCallback())
        kwargs["callbacks"] = callbacks
        self._fit(*args, **kwargs)

    if not run_once:
        run_once = True
        keras.engine.Model._fit = keras.engine.Model.fit
        keras.engine.Model.fit = fit
        # TODO: Need to be able to pass options to init?
        wandb.init()
