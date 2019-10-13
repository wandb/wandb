---
description: >-
  Here are common questions about using rich media with W&B, including logging
  images and video.
---

# Rich Media

**How do I log images from different epochs and compare them?**  
Each time you log images from a step, we save them to show in the UI. Pin the image panel, and use the **step slider** to look at images from different steps. This makes it easy to compare how a model's output changes over training.

**How do you log a PNG?**  
 If you're manually logging, we'll log a PNG with:

```text
wandb.log({"example": wandb.Image(...)})
```

  
**How do you log a JPEG?**  
We'll save a JPEG if you call:

```text
wandb.log({"example": [wandb.Image(...) for i in images]})
```

  
**Can you log a video?**  
Yes. You can see video files in the file pain and download them if you log them

**Can you pass multiple images through each epoch?**  

```text
wandb.log (image)
```

**How do you visualize training every N \(500\) iterations?**  
  I.E. log loss every 500 batches, and log validation images every 2500 batches

