from pathlib import Path


def test_dashboard_login_posts_email_field_expected_by_platform_api():
    auth_api = Path("dashboard/src/api/auth.ts").read_text()

    assert "JSON.stringify({ email: username, password })" in auth_api
