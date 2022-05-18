import threading

import wandb


# Checks if wandb has issues during set up in a multithreaded environment
def thread_test(n):
    run = wandb.init(project="threadtest")
    run.log({"thread": n})


def main():
    try:
        threads = []
        for i in range(2):
            threads.append(threading.Thread(target=thread_test, args=(i,)))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    except Exception as e:
        print(e)
        print("Issue with calling wandb init in a multithreaded situation")
        raise AssertionError("Issue with calling wandb init in a multithreaded situation")


if __name__ == "__main__":
    main()
