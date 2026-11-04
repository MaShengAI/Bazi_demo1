import pytest
from mysql_target import require_financial_test_database


def test_manual_target_still_works(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    require_financial_test_database(
        "mysql+pymysql://bazi_payment_tester:test@bazi-preprod-mysql-1:3306/bazi_payment_test"
    )


@pytest.mark.parametrize("port", [3306, 13307])
def test_ci_target_requires_explicit_github_environment(monkeypatch, port):
    url = f"mysql+pymysql://bazi_ci:test@127.0.0.1:{port}/bazi_ci_test"
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError):
        require_financial_test_database(url)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    require_financial_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://root:test@127.0.0.1:3306/bazi_ci_test",
        "mysql+pymysql://bazi_ci:test@127.0.0.1:3306/bazi",
        "mysql+pymysql://bazi_ci:test@production:3306/bazi_ci_test",
        "mysql+pymysql://bazi_ci:test@127.0.0.1:3307/bazi_ci_test",
        "sqlite:///bazi_ci_test",
    ],
)
def test_other_targets_rejected_even_in_ci(monkeypatch, url):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(ValueError):
        require_financial_test_database(url)
