#include <stdio.h>
#include <assert.h>

#include <libwandb.h>


int main(int argc, char **argv) {
    int i;
    int rc;
    wandb_run run;

    rc = wandb_init(&run);
    assert(rc == 0);

    for (i=0; i < 10; i++) {
        printf("log %d\n", i);
        wandb_log_scaler(&run, "key", i);
    }
    wandb_finish(&run);
    return 0;
}
