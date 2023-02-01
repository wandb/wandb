
# Modification steps

```shell
find . -type f -name \*.py | \
   xargs egrep "from watchdog[.]" | \
   sed s'/:.*//' | \
   xargs sed -i bak -e 's/^from watchdog[.]/from wandb_watchdog./'
```
