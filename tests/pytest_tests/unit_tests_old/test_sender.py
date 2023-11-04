import queue
import threading


def test_send_status_request_stopped(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True

    with backend_interface() as interface:
        handle = interface.deliver_stop_status()
        result = handle.wait(timeout=5)
        stop_status = result.response.stop_status_response
        assert result is not None
        assert stop_status.run_should_stop


def test_parallel_requests(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()

    with backend_interface() as interface:

        def send_sync_request(i):
            work_queue.get()
            if i % 3 == 0:
                handle = interface.deliver_stop_status()
                result = handle.wait(timeout=5)
                stop_status = result.response.stop_status_response
                assert stop_status is not None
                assert stop_status.run_should_stop
            elif i % 3 == 2:
                handle = interface.deliver_get_summary()
                result = handle.wait(timeout=5)
                summary = result.response.get_summary_response
                assert summary is not None
                assert hasattr(summary, "item")
            work_queue.task_done()

        for i in range(10):
            work_queue.put(None)
            t = threading.Thread(target=send_sync_request, args=(i,))
            t.daemon = True
            t.start()

        work_queue.join()


def test_send_status_request_network(mock_server, backend_interface):
    mock_server.ctx["rate_limited_times"] = 3

    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})

        handle = interface.deliver_network_status()
        result = handle.wait(timeout=5)
        assert result is not None
        network = result.response.network_status_response
        assert len(network.network_responses) > 0
        assert network.network_responses[0].http_status_code == 429
