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
HERE="$PWD"
for n in 1e2 3e2 1e3 3e3 1e4; do
    for s in 1e3 200e3; do
        DIR="runs/n=$n,s=$s,rand=$RANDOM"
        mkdir -p "$DIR"
        pushd "$DIR"
        python3 "$HERE/images-in-table-in-artifact.py" --n-images="$n" --image-bytes="$s" 2>&1 | tee run.log
        popd
    done
done
```
