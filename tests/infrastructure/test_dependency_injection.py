from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from monatise.infrastructure.dependency_injection import (
    Container,
    DependencyResolutionError,
    Lifetime,
)


def test_singleton_returns_same_instance() -> None:
    container = Container()
    container.register(
        "service",
        lambda _: object(),
        lifetime=Lifetime.SINGLETON,
    )

    first = container.resolve("service")
    second = container.resolve("service")

    assert first is second


def test_transient_returns_new_instances() -> None:
    container = Container()
    container.register(
        "service",
        lambda _: object(),
        lifetime=Lifetime.TRANSIENT,
    )

    first = container.resolve("service")
    second = container.resolve("service")

    assert first is not second


def test_scoped_lifetime_reuses_within_scope() -> None:
    container = Container()
    container.register(
        "request_state",
        lambda _: object(),
        lifetime=Lifetime.SCOPED,
    )

    with container.scope("analysis-run"):
        first = container.resolve("request_state")
        second = container.resolve("request_state")
        assert first is second

    with container.scope("second-run"):
        third = container.resolve("request_state")
        assert third is not first


def test_scoped_resolution_requires_scope() -> None:
    container = Container()
    container.register(
        "request_state",
        lambda _: object(),
        lifetime=Lifetime.SCOPED,
    )

    try:
        container.resolve("request_state")
    except DependencyResolutionError as exc:
        assert "requires an active scope" in str(exc)
    else:
        raise AssertionError("expected scoped dependency error")


def test_dependencies_can_be_resolved_by_factory() -> None:
    container = Container()
    container.register_instance("config", {"mode": "paper"})
    container.register(
        "service",
        lambda resolver: {
            "config": resolver.resolve("config"),
        },
        dependencies=("config",),
    )

    service = container.resolve("service")
    assert service["config"]["mode"] == "paper"


def test_missing_dependency_is_reported_by_graph_validation() -> None:
    container = Container()
    container.register(
        "service",
        lambda _: object(),
        dependencies=("missing",),
    )

    errors = container.validate_graph()
    assert any("unregistered" in error for error in errors)


def test_circular_dependency_is_detected() -> None:
    container = Container()
    container.register(
        "a",
        lambda resolver: resolver.resolve("b"),
        dependencies=("b",),
    )
    container.register(
        "b",
        lambda resolver: resolver.resolve("a"),
        dependencies=("a",),
    )

    errors = container.validate_graph()
    assert any("circular dependency" in error for error in errors)


def test_duplicate_registration_requires_replace() -> None:
    container = Container()
    container.register("service", lambda _: 1)

    try:
        container.register("service", lambda _: 2)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("expected duplicate registration error")

    container.register(
        "service",
        lambda _: 2,
        replace=True,
    )
    assert container.resolve("service") == 2


def test_container_is_non_executable() -> None:
    container = Container()

    assert not hasattr(container, "place_order")
    assert not hasattr(container, "submit_trade")
    assert not hasattr(container, "exchange_secret")


def test_scope_disposes_managed_instances() -> None:
    class Resource:
        closed = False

        def close(self):
            self.closed = True

    container = Container()
    container.register("resource", lambda _: Resource(), lifetime=Lifetime.SCOPED)

    with container.scope("request"):
        resource = container.resolve("resource")
        assert resource.closed is False

    assert resource.closed is True


def test_scopes_are_isolated_between_threads() -> None:
    container = Container()
    container.register("state", lambda _: object(), lifetime=Lifetime.SCOPED)
    barrier = Barrier(2)

    def resolve_in_scope(name):
        with container.scope(name):
            first = container.resolve("state")
            barrier.wait()
            second = container.resolve("state")
            return first, second

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(resolve_in_scope, "one")
        second_future = pool.submit(resolve_in_scope, "two")
        first = first_future.result()
        second = second_future.result()

    assert first[0] is first[1]
    assert second[0] is second[1]
    assert first[0] is not second[0]


def test_replacing_and_clearing_singletons_disposes_resources() -> None:
    class Resource:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    container = Container()
    first = Resource()
    second = Resource()
    container.register_instance("resource", first)
    container.register_instance("resource", second, replace=True)
    assert first.closed is True
    assert second.closed is False

    container.clear()
    assert second.closed is True


def test_scope_disposal_continues_after_one_resource_fails() -> None:
    disposed = []

    class Resource:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        def close(self):
            disposed.append(self.name)
            if self.fail:
                raise RuntimeError("close failed")

    container = Container()
    container.register_instance("first", object())
    container.register("a", lambda _: Resource("a"), lifetime=Lifetime.SCOPED)
    container.register("b", lambda _: Resource("b", True), lifetime=Lifetime.SCOPED)
    try:
        with container.scope("failure"):
            container.resolve("a")
            container.resolve("b")
    except DependencyResolutionError as exc:
        assert "disposal failed" in str(exc)
    else:
        raise AssertionError("expected disposal failure")
    assert disposed == ["b", "a"]
