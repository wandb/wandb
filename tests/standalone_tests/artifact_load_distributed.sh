python artifact_load.py \
  --gen_n_files 1000 \
  --gen_max_small_size 10000 \
  --gen_max_large_size 250000 \
  --test_phase_seconds 60 \
  --num_writers 2 \
  --distributed_fanout 3 \
  --files_per_version_min 10 \
  --files_per_version_max 100 \
  --num_readers 2
