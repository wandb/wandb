
# Modification steps

```shell
git checkout v2.3.0
mv promise wandb_promise
rm -rf .git
patch -p4 < wandb-vendor.diff
```
