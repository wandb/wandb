import wandb
import wandb.sdk.verify.verify as wandb_verify


def test_print_results(capsys):
    failed_test_or_tests = ["test1", "test2"]
    wandb_verify.print_results(None, warning=True)
    wandb_verify.print_results(failed_test_or_tests[0], warning=False)
    wandb_verify.print_results(failed_test_or_tests, warning=False)
    captured = capsys.readouterr().out
    assert u"\u2705" in captured
    assert u"\u274C" in captured
    assert captured.count(u"\u274C") == 2


def test_check_host():
    assert not wandb_verify.check_host("https://api.wandb.ai")
    assert wandb_verify.check_host("http://localhost:8000")

