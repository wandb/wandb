To get set up:

```bash
python3 generate-random-images.py 10000 images/
```

To upload a run with 1000 images:

```bash
python3 images-in-table-in-artifact.py 1000 images/
```

This generates a bunch of `.profile` files, which Python's `pstats` library can read/process/print for you:

```bash
view-stats() { python3 -c 'import pstats; stats = pstats.Stats("'"$1"'"); stats.sort_stats("cumtime").print_stats()'; }
view-stats run.profile  # or wandb_internal.profile or others
```
