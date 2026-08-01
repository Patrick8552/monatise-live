import asyncio

from monatise.infrastructure.plugin_framework import (
    PluginCapability,
    PluginContext,
    PluginDependency,
    PluginError,
    PluginManager,
    PluginManifest,
    PluginState,
)


class DummyPlugin:
    def __init__(
        self,
        name: str,
        *,
        version: str = "1.0.0",
        dependencies=(),
        capabilities=(PluginCapability.REPORTING,),
        enabled_by_default=False,
    ) -> None:
        self.manifest = PluginManifest(
            name=name,
            version=version,
            entrypoint=f"tests.fake:{name}",
            api_version=1,
            capabilities=capabilities,
            dependencies=dependencies,
            enabled_by_default=enabled_by_default,
        )
        self.registered = False
        self.started = False
        self.stopped = False

    def register(self, context) -> None:
        self.registered = True

    async def start(self, context) -> None:
        self.started = True

    async def stop(self, context) -> None:
        self.stopped = True


def context() -> PluginContext:
    return PluginContext(
        container=object(),
        event_bus=object(),
        configuration=object(),
    )


def test_plugin_lifecycle() -> None:
    async def run() -> None:
        plugin = DummyPlugin("reporter")
        manager = PluginManager(context=context())
        manager.add(plugin)

        manager.load("reporter")
        assert plugin.registered is True

        await manager.start("reporter")
        assert plugin.started is True
        assert manager.registrations[0].state is PluginState.STARTED

        await manager.stop("reporter")
        assert plugin.stopped is True
        assert manager.registrations[0].state is PluginState.STOPPED

    asyncio.run(run())


def test_missing_dependency_is_rejected() -> None:
    plugin = DummyPlugin(
        "dependent",
        dependencies=(PluginDependency("missing"),),
    )
    manager = PluginManager(context=context())
    manager.add(plugin)

    try:
        manager.validate("dependent")
    except PluginError as exc:
        assert "missing plugin dependency" in str(exc)
    else:
        raise AssertionError("expected dependency failure")


def test_dependency_version_is_checked() -> None:
    base = DummyPlugin("base", version="1.0.0")
    dependent = DummyPlugin(
        "dependent",
        dependencies=(
            PluginDependency("base", minimum_version="2.0.0"),
        ),
    )
    manager = PluginManager(context=context())
    manager.add(base)
    manager.add(dependent)

    try:
        manager.validate("dependent")
    except PluginError as exc:
        assert "requires version" in str(exc)
    else:
        raise AssertionError("expected version failure")


def test_manifest_requires_semantic_version_and_entrypoint() -> None:
    plugin = DummyPlugin("invalid", version="1")
    manager = PluginManager(context=context())

    try:
        manager.add(plugin)
    except PluginError as exc:
        assert "semantic version" in str(exc)
    else:
        raise AssertionError("expected manifest failure")

    plugin.manifest = PluginManifest(
        name="invalid",
        version="1.0.0",
        entrypoint="not-an-entrypoint",
        api_version=1,
        capabilities=(PluginCapability.REPORTING,),
    )
    try:
        manager.add(plugin)
    except PluginError as exc:
        assert "module:object" in str(exc)
    else:
        raise AssertionError("expected entrypoint failure")


def test_forbidden_capability_is_rejected() -> None:
    plugin = DummyPlugin(
        "market",
        capabilities=(PluginCapability.MARKET_DATA,),
    )
    manager = PluginManager(
        context=context(),
        allowed_capabilities=(PluginCapability.REPORTING,),
    )
    manager.add(plugin)

    try:
        manager.validate("market")
    except PluginError as exc:
        assert "forbidden capabilities" in str(exc)
    else:
        raise AssertionError("expected capability failure")


def test_start_all_respects_dependencies() -> None:
    async def run() -> None:
        base = DummyPlugin(
            "base",
            enabled_by_default=True,
        )
        dependent = DummyPlugin(
            "dependent",
            dependencies=(PluginDependency("base"),),
            enabled_by_default=True,
        )
        manager = PluginManager(context=context())
        manager.add(dependent)
        manager.add(base)

        started = await manager.start_all()
        assert tuple(item.manifest.name for item in started) == (
            "base",
            "dependent",
        )

    asyncio.run(run())


def test_enabled_plugin_cannot_start_with_disabled_dependency() -> None:
    async def run() -> None:
        base = DummyPlugin("base", enabled_by_default=False)
        dependent = DummyPlugin(
            "dependent",
            dependencies=(PluginDependency("base"),),
            enabled_by_default=True,
        )
        manager = PluginManager(context=context())
        manager.add(base)
        manager.add(dependent)

        try:
            await manager.start_all()
        except PluginError as exc:
            assert "unavailable dependencies" in str(exc)
        else:
            raise AssertionError("expected unavailable dependency failure")

    asyncio.run(run())


def test_start_all_rolls_back_plugins_started_in_transaction() -> None:
    class FailingPlugin(DummyPlugin):
        async def start(self, context) -> None:
            raise RuntimeError("boom")

    async def run() -> None:
        base = DummyPlugin("base", enabled_by_default=True)
        failing = FailingPlugin(
            "failing",
            dependencies=(PluginDependency("base"),),
            enabled_by_default=True,
        )
        manager = PluginManager(context=context())
        manager.add(base)
        manager.add(failing)

        try:
            await manager.start_all()
        except PluginError as exc:
            assert "startup transaction failed" in str(exc)
        else:
            raise AssertionError("expected startup failure")

        assert base.stopped is True
        assert manager.registrations[0].state is PluginState.STOPPED

    asyncio.run(run())


def test_dependency_cannot_stop_before_started_dependent() -> None:
    async def run() -> None:
        base = DummyPlugin("base")
        dependent = DummyPlugin(
            "dependent",
            dependencies=(PluginDependency("base"),),
        )
        manager = PluginManager(context=context())
        manager.add(base)
        manager.add(dependent)
        await manager.start("base")
        await manager.start("dependent")

        try:
            await manager.stop("base")
        except PluginError as exc:
            assert "dependents are started" in str(exc)
        else:
            raise AssertionError("expected dependency safety failure")

    asyncio.run(run())


def test_disabled_plugin_can_be_reenabled_without_reregistering() -> None:
    async def run() -> None:
        plugin = DummyPlugin("reporter")
        manager = PluginManager(context=context())
        manager.add(plugin)
        manager.load("reporter")
        manager.disable("reporter")

        registration = manager.enable("reporter")
        assert registration.state is PluginState.LOADED
        await manager.start("reporter")
        assert plugin.started is True

    asyncio.run(run())


def test_concurrent_start_is_idempotent() -> None:
    async def run() -> None:
        plugin = DummyPlugin("reporter")
        manager = PluginManager(context=context())
        manager.add(plugin)

        first, second = await asyncio.gather(
            manager.start("reporter"),
            manager.start("reporter"),
        )
        assert first.manifest.name == second.manifest.name
        assert first.state is PluginState.STARTED

    asyncio.run(run())


def test_registration_views_cannot_corrupt_manager_state() -> None:
    plugin = DummyPlugin("reporter")
    manager = PluginManager(context=context())
    added = manager.add(plugin)
    added.state = PluginState.FAILED

    listed = manager.registrations[0]
    assert listed.state is PluginState.DISCOVERED
    listed.state = PluginState.DISABLED
    assert manager.registrations[0].state is PluginState.DISCOVERED


def test_cycle_detection() -> None:
    first = DummyPlugin(
        "first",
        dependencies=(PluginDependency("second"),),
    )
    second = DummyPlugin(
        "second",
        dependencies=(PluginDependency("first"),),
    )
    manager = PluginManager(context=context())
    manager.add(first)
    manager.add(second)

    try:
        asyncio.run(manager.start_all())
    except PluginError as exc:
        assert "circular plugin dependency" in str(exc)
    else:
        raise AssertionError("expected cycle failure")


def test_framework_has_no_execution_capability() -> None:
    manager = PluginManager(context=context())

    assert manager.execution_capability_available is False
    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")
