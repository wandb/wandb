#!/usr/bin/env python
import multiprocessing

import wandb


def run_proc(id=0):
    st = wandb.StreamTable("test/test/streamtable")
    for i in range(10):
        st.log({"a": i, "b": i * 2, "c": i * 3, "id": id})

    st.finish()


if __name__ == "__main__":
    p1 = multiprocessing.Process(target=run_proc, args=(1,))
    p2 = multiprocessing.Process(target=run_proc, args=(2,))

    p1.start()
    p2.start()

    p1.join()
    p2.join()
