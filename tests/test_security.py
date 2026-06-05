from app.security import hash_password, verify_password


def test_hash_then_verify_succeeds():
    h = hash_password("secret")
    assert h != "secret"
    assert verify_password("secret", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("secret")
    assert verify_password("wrong", h) is False
