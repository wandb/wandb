from promise import Promise
from promise.dataloader import DataLoader
import threading



def test_promise_thread_safety():
    """
    Promise tasks should never be executed in a different thread from the one they are scheduled from,
    unless the ThreadPoolExecutor is used.

    Here we assert that the pending promise tasks on thread 1 are not executed on thread 2 as thread 2 
    resolves its own promise tasks.
    """
    event_1 = threading.Event()
    event_2 = threading.Event()

    assert_object = {'is_same_thread': True}

    def task_1():
        thread_name = threading.current_thread().getName()

        def then_1(value): 
          # Enqueue tasks to run later. 
          # This relies on the fact that `then` does not execute the function synchronously when called from
          # within another `then` callback function.
          promise = Promise.resolve(None).then(then_2)
          assert promise.is_pending
          event_1.set()  # Unblock main thread
          event_2.wait()  # Wait for thread 2 
       
        def then_2(value):
          assert_object['is_same_thread'] = (thread_name == threading.current_thread().getName())

        promise = Promise.resolve(None).then(then_1)

    def task_2():
        promise = Promise.resolve(None).then(lambda v: None)
        promise.get()  # Drain task queue
        event_2.set()  # Unblock thread 1

    thread_1 = threading.Thread(target=task_1)
    thread_1.start()

    event_1.wait()  # Wait for Thread 1 to enqueue promise tasks

    thread_2 = threading.Thread(target=task_2)  
    thread_2.start()

    for thread in (thread_1, thread_2):
      thread.join()

    assert assert_object['is_same_thread']


def test_dataloader_thread_safety():
    """
    Dataloader should only batch `load` calls that happened on the same thread.
    
    Here we assert that `load` calls on thread 2 are not batched on thread 1 as
    thread 1 batches its own `load` calls.
    """
    def load_many(keys):
        thead_name = threading.current_thread().getName()
        return Promise.resolve([thead_name for key in keys])

    thread_name_loader = DataLoader(load_many)

    event_1 = threading.Event()
    event_2 = threading.Event()
    event_3 = threading.Event()

    assert_object = {
      'is_same_thread_1': True,
      'is_same_thread_2': True,
    }

    def task_1():
        @Promise.safe
        def do():
            promise = thread_name_loader.load(1)
            event_1.set()
            event_2.wait()  # Wait for thread 2 to call `load`
            assert_object['is_same_thread_1'] = (
              promise.get() == threading.current_thread().getName()
            )
            event_3.set()  # Unblock thread 2

        do().get()

    def task_2():
        @Promise.safe
        def do():
            promise = thread_name_loader.load(2)
            event_2.set()
            event_3.wait()  # Wait for thread 1 to run `dispatch_queue_batch`
            assert_object['is_same_thread_2'] = (
              promise.get() == threading.current_thread().getName()
            )
            
        do().get()

    thread_1 = threading.Thread(target=task_1)
    thread_1.start()

    event_1.wait() # Wait for thread 1 to call `load`

    thread_2 = threading.Thread(target=task_2)  
    thread_2.start()

    for thread in (thread_1, thread_2):
      thread.join()

    assert assert_object['is_same_thread_1']
    assert assert_object['is_same_thread_2']
