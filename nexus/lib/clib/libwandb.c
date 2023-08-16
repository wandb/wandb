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
    /*
    int d = nexus_recv(n);
    nexus_run_start(n);
    int d2 = nexus_recv(n);
    */
    return 0;
}

// void wandb_history_clear(wandb_history *history) {
// }

// void wandb_history_add_float(wandb_history *history, char *key, float value) {
// }

// void wandb_history_step(wandb_history *history, int step) {
// }

void wandb_log_scaler(wandb_run *run, char *key, float value) {
    int num = run->num;
    wandbcore_log_scaler(num, key, value);
}

void wandb_finish(wandb_run *run) {
    int num = run->num;
    wandbcore_finish(num);
    /*
    int d = nexus_recv(num);
    */
}

void wandb_teardown() {
    wandbcore_teardown();
}
