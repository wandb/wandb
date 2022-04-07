To get set up:

```bash
python3 generate-random-images.py 10000 images/
```

To upload a run with 1000 images:

```bash
python3 images-in-table-in-artifact.py --n-images=1e3 --image-bytes=20e3
```

This generates a bunch of `.profile` files, which Python's `pstats` library can read/process/print for you:

```bash
view-stats() { python3 -c 'import pstats; stats = pstats.Stats("'"$1"'"); stats.sort_stats("cumtime").print_stats()'; }
view-stats run.profile  # or wandb_internal.profile or others
```

To run this at many different scales:
```bash
python3 cartesian-product.py \
    --n-images 1 10 100 \
    --image-kb 1 10 100 \
    --double-log True False \
    --all-in-memory-at-once-threshold-kb=1e6
```
