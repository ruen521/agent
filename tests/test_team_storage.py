from __future__ import annotations

from pathlib import Path

from app.db.mysql_repository import MysqlRepository


def test_team_storage_create_tables_idempotent() -> None:
    repo = MysqlRepository("sqlite+pysqlite:///:memory:")
    repo.create_tables()
    repo.create_tables()



def test_team_shared_state_version_increment() -> None:
    repo = MysqlRepository("sqlite+pysqlite:///:memory:")
    repo.create_tables()

    repo.upsert_team_shared_state(
        run_id="run-1",
        key="stockout_risks",
        value={"count": 1},
        version=1,
        producer_member="stockout_sentinel",
    )
    repo.upsert_team_shared_state(
        run_id="run-1",
        key="stockout_risks",
        value={"count": 2},
        version=2,
        producer_member="stockout_sentinel",
    )

    state = repo.get_team_shared_state("run-1")
    assert state["stockout_risks"]["version"] == 2
    assert state["stockout_risks"]["value"]["count"] == 2



def test_team_artifact_index_matches_file(tmp_path: Path) -> None:
    repo = MysqlRepository("sqlite+pysqlite:///:memory:")
    repo.create_tables()

    run_dir = tmp_path / "team_runs" / "run-2"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "member_1_report.txt"
    artifact_path.write_text("artifact content", encoding="utf-8")

    artifact_id = repo.save_team_artifact(
        run_id="run-2",
        member_id="stockout_sentinel",
        kind="report",
        file_name=artifact_path.name,
        file_path=str(artifact_path),
        content_type="text/plain",
        artifact_meta={"source": "unit_test"},
    )

    artifacts = repo.list_team_artifacts("run-2")
    assert artifact_id == artifacts[0]["id"]
    assert Path(artifacts[0]["file_path"]).exists()
