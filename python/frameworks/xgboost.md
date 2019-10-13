# XGBoost

You can use our XGBoost callback to monitor stats while training.

```text
bst = xgb.train(param, xg_train, num_round, watchlist, 
                callbacks=[wandb.xgboost.wandb_callback()])
```

Check out our [GitHub repo](https://github.com/wandb/examples) for complete example code.

