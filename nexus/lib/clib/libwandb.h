// typedef int (*finish_func)(int exit_code);

struct wandb_run_s {
    int num;
};

// struct wandb_history_s {
// };

typedef struct wandb_run_s wandb_run;
// typedef struct wandb_history_s wandb_history;


int wandb_init(wandb_run *run);
// void wandb_history_clear(wandb_history *history);
// void wandb_history_add_float(wandb_history *history, char *key, float value);
// void wandb_history_step(wandb_history *history, int step);
// void wandb_log(wandb_run *run, wandb_history *hist);
void wandb_log_scaler(wandb_run *run, char *key, float value);
void wandb_finish(wandb_run *run);
void wandb_setup();
void wandb_teardown();
