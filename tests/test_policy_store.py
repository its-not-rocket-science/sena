from sena.core.models import PolicyBundleMetadata
from sena.policy.parser import load_policy_bundle
from sena.policy.store import SQLitePolicyBundleRepository


def test_sqlite_repository_register_activate_and_fetch(tmp_path) -> None:
    db_path = tmp_path / "registry.db"
    repo = SQLitePolicyBundleRepository(str(db_path))
    repo.initialize()

    rules, metadata = load_policy_bundle("src/sena/examples/policies")
    metadata = PolicyBundleMetadata(
        bundle_name=metadata.bundle_name,
        version=metadata.version,
        loaded_from=metadata.loaded_from,
        lifecycle="candidate",
    )

    bundle_id = repo.register_bundle(metadata, rules)
    repo.set_bundle_lifecycle(bundle_id, "active")

    active = repo.get_active_bundle(metadata.bundle_name)
    assert active is not None
    assert active.id == bundle_id
    assert active.metadata.lifecycle == "active"
    assert len(active.rules) == len(rules)
