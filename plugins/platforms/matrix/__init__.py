from .adapter import register as _register_adapter


def register(ctx) -> None:
    _register_adapter(ctx)
    from .space_mirror import register as register_space_mirror
    register_space_mirror(ctx)


__all__ = ["register"]
