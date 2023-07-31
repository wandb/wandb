#!/usr/bin/env python

import wandb

st = wandb.StreamTable("test/test/streamtable")
for i in range(10):
    st.log({"a": i, "b": i * 2, "c": i * 3})

st.finish()
