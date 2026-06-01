import json
import os
from auth import hash_password, verify_password


class UserStore:
    def __init__(self, filepath: str):
        self._filepath = filepath
        self._users: dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(self._filepath):
            with open(self._filepath, 'r') as f:
                self._users = json.load(f)

    def _save(self):
        os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
        with open(self._filepath, 'w') as f:
            json.dump(self._users, f)

    def add_user(self, username: str, password: str):
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        salt, h = hash_password(password)
        self._users[username] = {"salt": salt, "hash": h}
        self._save()

    def remove_user(self, username: str):
        if username in self._users:
            del self._users[username]
            self._save()

    def list_users(self) -> list[str]:
        return list(self._users.keys())

    def verify(self, username: str, password: str) -> bool:
        entry = self._users.get(username)
        if not entry:
            return False
        return verify_password(password, entry["salt"], entry["hash"])

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        if not self.verify(username, old_password):
            return False
        salt, h = hash_password(new_password)
        self._users[username] = {"salt": salt, "hash": h}
        self._save()
        return True
