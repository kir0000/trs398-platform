import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()
MIN_PASSWORD_LENGTH = 10

ROLES = ("viewer", "physicist", "reviewer", "admin")
ROLE_LABELS = {"viewer": "наблюдатель", "physicist": "физик", "reviewer": "проверяющий", "admin": "администратор"}


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def can_create(role: str) -> bool:
    return role in ("physicist", "admin")


def can_review(role: str) -> bool:
    return role in ("reviewer", "admin")


class LoginThrottle:
    """Lock a login for a while after repeated failures (in memory, per process)."""

    def __init__(self, max_failures=5, window_s=300):
        self.max_failures, self.window_s = max_failures, window_s
        self._fails = defaultdict(list)

    def blocked(self, login: str) -> bool:
        now = time.time()
        self._fails[login] = [t for t in self._fails[login] if now - t < self.window_s]
        return len(self._fails[login]) >= self.max_failures

    def fail(self, login: str):
        self._fails[login].append(time.time())

    def reset(self, login: str):
        self._fails.pop(login, None)
