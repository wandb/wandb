python artifact_load.py \
  --gen_n_files 100000 \
  --gen_max_small_size 10000 \
  --gen_max_large_size 250000 \
  --test_phase_seconds 60 \
  --num_writers 10 \
  --files_per_version_min 10 \
  --files_per_version_max 1000 \
  --num_readers 10