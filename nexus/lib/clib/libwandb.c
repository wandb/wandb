#include <stdio.h>
#include <stdlib.h>
#include <libwandb.h>
#include <libwandbcore.h>

void wandb_setup() {
    wandbcore_setup();
    atexit(wandb_teardown);
}

int wandb_init(wandb_run *run) {
    wandb_setup();
    int n = wandbcore_init();
    run->num = n;
    return 0;
}

void wandb_log_scaler(wandb_run *run, char *key, float value) {
    int num = run->num;
    wandbcore_log_scaler(num, key, value);
}

void wandb_finish(wandb_run *run) {
    int num = run->num;
    wandbcore_finish(num);
}

void wandb_teardown() {
    wandbcore_teardown();
}
