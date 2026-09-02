from app.services.account_store import Account, AccountStore


def test_account_store_roundtrip(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json")
    store.save(
        [
            Account(
                username="alice",
                password="secret",
                remember_password=True,
                auto_login=True,
            )
        ],
        last_username="alice",
    )

    accounts = store.load()

    assert len(accounts) == 1
    assert accounts[0].username == "alice"
    assert accounts[0].password == "secret"
    assert accounts[0].remember_password is True
    assert accounts[0].auto_login is True
    assert store.load_last_username() == "alice"
