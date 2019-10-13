# Grouping

W&B provides the ability to group runs up to two levels. This is useful for distributed training or combining multiple process types. 

After you've run a run, our web interface lets you select any **config** variable and group runs that share the same value in that column. 

If you'd like to specify grouping before you launch experiments, you have a couple options.

1. [Environment Variable](environment-variables.md): Use the`WANDB_RUN_GROUP` environment variable
2. Pass arguments to [wandb.init](../library/init.md):
   * For a single level of grouping, set the **group** argument
   * For a second level of grouping, set the **job\_type** argument

