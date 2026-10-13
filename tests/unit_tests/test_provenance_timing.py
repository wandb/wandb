def test_cuda_queue_never_synchronizes_and_bounds_pending():
    from wandb.sdk.provenance.timing import CudaEventQueue

    class Event:
        ready = False

        def record(self):
            pass

        def query(self):
            return self.ready

        def elapsed_time(self, other):
            return 2.5

        def synchronize(self):
            raise AssertionError("synchronize called")

    queue = CudaEventQueue(Event, capacity=2)
    for step in range(4):
        token = queue.start("forward_backward", step)
        queue.finish(token)
    assert queue.completed() == []
    assert queue.dropped == 2
    Event.ready = True
    assert [phase.duration_ms for phase in queue.completed()] == [2.5, 2.5]
