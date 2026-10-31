import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_and_staging_reject_the_development_admin_token():
    for environment in ("production", "staging"):
        with pytest.raises(ValidationError, match="ADMIN_TOKEN must be changed"):
            Settings(app_env=environment)


def test_non_development_environment_accepts_a_replaced_admin_token():
    settings = Settings(app_env="production", admin_token="deployment-secret-value")
    assert settings.admin_token == "deployment-secret-value"
