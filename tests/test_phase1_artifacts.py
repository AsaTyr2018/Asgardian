from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_helm_chart_excludes_control_plane_and_uses_nfs():
    helpers = (ROOT / "deploy/helm/asgardian/templates/_helpers.tpl").read_text(encoding="utf-8")
    values = (ROOT / "deploy/helm/asgardian/values.yaml").read_text(encoding="utf-8")
    postgres = (ROOT / "deploy/helm/asgardian/templates/postgres.yaml").read_text(encoding="utf-8")

    assert "node-role.kubernetes.io/control-plane" in helpers
    assert "operator: DoesNotExist" in helpers
    assert "storageClass: standard" in values
    assert "storageClassName:" in postgres


def test_build_policy_requires_worker_label_and_excludes_control_plane():
    policy = (ROOT / "deploy/policies/asgardian-worker-affinity.yaml").read_text(encoding="utf-8")

    assert 'asgardian.io/build: "true"' in policy
    assert "node-role.kubernetes.io/control-plane" in policy
    assert "tolerations" not in policy


def test_api_has_bounded_writable_multipart_spool():
    manifest = (ROOT / "deploy/kubernetes/20-app.yaml").read_text(encoding="utf-8")
    chart = (ROOT / "deploy/helm/asgardian/templates/backend.yaml").read_text(encoding="utf-8")

    for deployment in (manifest, chart):
        assert "mountPath: /tmp" in deployment
        assert "emptyDir: { sizeLimit: 64Mi }" in deployment


def test_initial_migration_covers_current_tables():
    migration = (ROOT / "migrations/versions/0001_initial.py").read_text(encoding="utf-8")

    assert '"walls"' in migration
    assert '"generation_jobs"' in migration
    assert "ix_generation_jobs_claim" in migration

    seed_migration = (ROOT / "migrations/versions/0002_seed_bigint.py").read_text(encoding="utf-8")
    assert "sa.BigInteger()" in seed_migration

    library_migration = (ROOT / "migrations/versions/0003_batches_and_library.py").read_text(encoding="utf-8")
    assert '"saved_assets"' in library_migration
    assert '"batch_id"' in library_migration
