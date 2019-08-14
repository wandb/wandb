import wandb
import time
from random import random
import cProfile

wandb.init(entity="vanpelt")

#Repeatedly logs random values


def log_stuff(n_to_write, log_wait, do_log=True):
    for i in range(n_to_write):
        rand_f = random()
        if do_log:
            wandb.log({'test': rand_f}, sync=False)
        time.sleep(log_wait)


#Loop and write to wandb every 5ms
n_to_write = 1000
log_wait = 0.005
start_log = time.perf_counter()
log_stuff(n_to_write, log_wait, True)
end_log = time.perf_counter()

#Run same loop without logging
start_nlog = time.perf_counter()
log_stuff(n_to_write, log_wait, False)
end_nlog = time.perf_counter()

print("That took " + str(end_log - start_log) + " seconds, without log it took " + str(end_nlog - start_nlog) + " seconds")
