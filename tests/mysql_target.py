"""Only allow the dedicated manual test DB or the ephemeral GitHub CI service."""

import os

from sqlalchemy.engine import make_url


def require_financial_test_database(url: str) -> None:
    parsed = make_url(url)
    manual = (
        parsed.database == "bazi_payment_test"
        and parsed.username == "bazi_payment_tester"
        and parsed.host == "bazi-preprod-mysql-1"
        and parsed.port == 3306
    )
    github = (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and parsed.database == "bazi_ci_test"
        and parsed.username == "bazi_ci"
        and parsed.host == "127.0.0.1"
        # 13307 is the isolated local mirror; never use a developer's default DB.
        and parsed.port in {3306, 13307}
    )
    if parsed.get_backend_name() != "mysql" or not (manual or github):
        raise ValueError("Requires the dedicated test database/user or GitHub CI MySQL service")
