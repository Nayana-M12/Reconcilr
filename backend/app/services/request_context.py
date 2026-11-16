from contextvars import ContextVar, Token

_audit_actor: ContextVar[str | None] = ContextVar("audit_actor", default=None)


def set_audit_actor(actor: str) -> Token[str | None]:
    return _audit_actor.set(actor)


def reset_audit_actor(token: Token[str | None]) -> None:
    _audit_actor.reset(token)


def current_audit_actor() -> str | None:
    return _audit_actor.get()
