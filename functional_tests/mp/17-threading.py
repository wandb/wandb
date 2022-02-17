from threading import Thread
import wandb


def do_run(id):
    run = wandb.init(settings=wandb.Settings(start_method="thread"))
    run.config.id = id
    run.log({"s": id})


def main():
    wandb.require("service")
    wandb.setup()
    threads = []
    for i in range(2):
        thread = Thread(target=do_run, args=(i,))
        thread.start()
        threads.append(thread)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
