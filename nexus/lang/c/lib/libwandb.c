#include <stdio.h>
#include <stdlib.h>
#include <libwandb.h>
#include <libwandb_core.h>

void wandb_setup() {
    wandbcoreSetup();
    atexit(wandb_teardown);
}

int wandb_init(wandb_run *run) {
    wandb_setup();
    int n = wandbcoreInit();
    run->num = n;
    return 0;
}

void wandb_log_scaler(wandb_run *run, char *key, float value) {
    int num = run->num;
    wandbcoreLogScaler(num, key, value);
}

void wandb_finish(wandb_run *run) {
    int num = run->num;
    wandbcoreFinish(num);
}

void wandb_teardown() {
    wandbcoreTeardown();
}
