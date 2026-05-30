import threading

from apps.worker.main import run_worker


def test_worker_logs_waiting_for_jobs(capsys) -> None:
    stop = threading.Event()
    stop.set()  # exit the idle loop immediately
    run_worker(worker_id="worker-test", kinds="package.build,source.fetch", stop=stop)
    out = capsys.readouterr().out
    assert "waiting for jobs" in out
    assert "worker-test" in out
