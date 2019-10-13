---
description: How to integrate a PyTorch script to log metrics to W&B
---

# PyTorch

W&B provides first class support for PyTorch. To automatically log gradients and store the network topology, you can call `watch` and pass in your PyTorch model.

```text
import wandb
wandb.init(config=args)

# Magic
wandb.watch(model)

model.train()
for batch_idx, (data, target) in enumerate(train_loader):
    output = model(data)
    loss = F.nll_loss(output, target)
    loss.backward()
    optimizer.step()
    if batch_idx % args.log_interval == 0:
        wandb.log({"loss": loss})
```

> Gradients, metrics and the graph won't be logged until `wandb.log` is called after a forward and backward pass.

See our [example projects](../example-projects/) for a complete script example.

#### Options

By default the hook only logs gradients. If you want to log histograms of parameter values as well, you can specify `wandb.watch(model, log="all")`. Valid options for the log argument are: "gradients", "parameters", "all", or None.

### Images

You can pass PyTorch tensors with image data into `wandb.Image` and torchvision utils will be used to log them automatically.

