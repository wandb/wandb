struct wandb_run_s {
    int num;
};

typedef struct wandb_run_s wandb_run;

int wandb_init(wandb_run *run);
void wandb_log_scaler(wandb_run *run, const char *key, double value);
void wandb_finish(wandb_run *run);
void wandb_setup();
void wandb_teardown();
