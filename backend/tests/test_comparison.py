import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models import Customer, Dataset, Segment, SegmentRun
from src.services.comparison_service import compare_runs


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def make_dataset(db, name, codes):
    dataset = Dataset(name=name, source_file=f"{name}.csv")
    db.add(dataset)
    db.flush()
    customers = {}
    for code in codes:
        customer = Customer(dataset_id=dataset.id, code=code, recency=10, frequency=5, spend=500, learning_days=5)
        db.add(customer)
        customers[code] = customer
    db.flush()
    return dataset, customers


def make_run(db, name, dataset, groups, status="completed"):
    run = SegmentRun(name=name, dataset_id=dataset.id, features=["recency", "spend"], k_min=2, k_max=2, status=status)
    db.add(run)
    db.flush()
    for label, (group_name, codes) in enumerate(groups):
        db.add(Segment(
            run_id=run.id, label=label, name=group_name, size=len(codes),
            center={"recency": 10, "spend": 500},
            customer_ids=[customer.id for customer in codes], recommendation="",
        ))
    db.commit()
    return run


def test_swapped_group_numbers_are_not_migration(db):
    dataset, customers = make_dataset(db, "d1", ["A1", "A2", "A3", "A4"])
    group_a = [customers[c] for c in ["A1", "A2"]]
    group_b = [customers[c] for c in ["A3", "A4"]]
    run_a = make_run(db, "run a", dataset, [("轻量", group_a), ("稳定", group_b)])
    run_b = make_run(db, "run b", dataset, [("稳定", group_b), ("轻量", group_a)])

    result = compare_runs(db, run_a.id, run_b.id)

    assert result["comparable"] is True
    assert result["summary"]["common"] == 4
    assert result["summary"]["migrated"] == 0
    assert result["summary"]["retained"] == 4
    assert result["summary"]["migration_share_of_common"] == 0.0
    assert result["summary"]["reconciled"] is True
    assert result["added_codes"] == []
    assert result["left_codes"] == []
    pairs = {(m["a_label"], m["b_label"]) for m in result["matches"]}
    assert pairs == {(0, 1), (1, 0)}
    assert all(m["label_changed"] for m in result["matches"])
    assert any("编号发生变化" in note for note in result["notes"])


def test_added_left_and_migration_across_datasets(db):
    dataset_a, ca = make_dataset(db, "d a", ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"])
    dataset_b, cb = make_dataset(db, "d b", ["A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12"])
    run_a = make_run(db, "run a", dataset_a, [
        ("轻量", [ca[c] for c in ["A1", "A2", "A3", "A4", "A5"]]),
        ("稳定", [ca[c] for c in ["A6", "A7", "A8", "A9", "A10"]]),
    ])
    run_b = make_run(db, "run b", dataset_b, [
        ("稳定", [cb[c] for c in ["A3", "A4", "A5", "A6", "A7", "A11"]]),
        ("轻量", [cb[c] for c in ["A8", "A9", "A10", "A12"]]),
    ])

    result = compare_runs(db, run_a.id, run_b.id)

    summary = result["summary"]
    assert result["comparable"] is True
    assert summary["common"] == 8
    assert summary["retained"] == 6
    assert summary["migrated"] == 2
    assert summary["added"] == 2
    assert summary["left"] == 2
    assert result["added_codes"] == ["A11", "A12"]
    assert result["left_codes"] == ["A1", "A2"]
    assert summary["reconciled"] is True
    # A 期总人数 = 留在对应群 + 迁移 + 离开；B 期总人数 = 留在对应群 + 迁移 + 新增
    assert summary["retained"] + summary["migrated"] + summary["left"] == result["run_a"]["total"]
    assert summary["retained"] + summary["migrated"] + summary["added"] == result["run_b"]["total"]
    migrations = {(m["a_label"], m["b_label"]): m["count"] for m in result["migrations"]}
    assert migrations == {(1, 0): 2}
    assert any(m["count"] == 2 and m["a_name"] == "稳定" and m["b_name"] == "稳定" for m in result["migrations"])
    # 迁移人数占比分别按共同客户、A 期和 B 期给出
    assert summary["migration_share_of_common"] == 0.25
    assert summary["migration_share_of_a"] == 0.2
    assert summary["migration_share_of_b"] == 0.2


def test_different_group_counts_are_supported(db):
    dataset, customers = make_dataset(db, "same", ["A1", "A2", "A3", "A4", "A5", "A6"])
    run_a = make_run(db, "2 groups", dataset, [
        ("轻量", [customers[c] for c in ["A1", "A2", "A3"]]),
        ("稳定", [customers[c] for c in ["A4", "A5", "A6"]]),
    ])
    run_b = make_run(db, "3 groups", dataset, [
        ("轻量", [customers[c] for c in ["A1", "A2"]]),
        ("稳定", [customers[c] for c in ["A3", "A4"]]),
        ("活跃", [customers[c] for c in ["A5", "A6"]]),
    ])

    result = compare_runs(db, run_a.id, run_b.id)

    assert result["run_a"]["group_count"] == 2
    assert result["run_b"]["group_count"] == 3
    assert result["summary"]["reconciled"] is True
    assert result["summary"]["retained"] + result["summary"]["migrated"] == 6
    # A 期每个群至多匹配一个 B 期群组；共同客户最多的 B 期群组优先
    matched = [m for m in result["matches"] if m["a_label"] is not None and m["b_label"] is not None]
    assert len(matched) == 2
    assert result["summary"]["retained"] == 4
    unmatched_b = [m for m in result["matches"] if m["a_label"] is None]
    assert len(unmatched_b) == 1
    assert unmatched_b[0]["b_label"] == 1
    assert unmatched_b[0]["b_size"] == 2
    assert any("两期群数不同" in note for note in result["notes"])


def test_no_common_customers_is_not_comparable(db):
    dataset_a, _ = make_dataset(db, "early", ["A1", "A2", "A3", "A4"])
    dataset_b, _ = make_dataset(db, "late", ["B1", "B2", "B3", "B4", "B5"])
    run_a = make_run(db, "run a", dataset_a, [
        ("轻量", [db.query(Customer).filter_by(dataset_id=dataset_a.id, code=c).one() for c in ["A1", "A2"]]),
        ("稳定", [db.query(Customer).filter_by(dataset_id=dataset_a.id, code=c).one() for c in ["A3", "A4"]]),
    ])
    run_b = make_run(db, "run b", dataset_b, [
        ("轻量", [db.query(Customer).filter_by(dataset_id=dataset_b.id, code=c).one() for c in ["B1", "B2"]]),
        ("稳定", [db.query(Customer).filter_by(dataset_id=dataset_b.id, code=c).one() for c in ["B3", "B4", "B5"]]),
    ])

    result = compare_runs(db, run_a.id, run_b.id)

    assert result["comparable"] is False
    assert "没有共同" in result["reason"]
    assert result["matches"] == []
    assert result["matrix"] == []
    assert result["migrations"] == []
    # 没有共同客户时不做迁移/新增/离开的推测
    assert result["added_codes"] == []
    assert result["left_codes"] == []
    assert result["run_a"]["total"] == 4
    assert result["run_b"]["total"] == 5


def test_unfinished_and_identical_runs_are_rejected(db):
    dataset, customers = make_dataset(db, "d", ["A1", "A2"])
    run_a = make_run(db, "done", dataset, [("轻量", customers.values()), ("稳定", [])])
    run_b = make_run(db, "queued", dataset, [("轻量", []), ("稳定", [])], status="queued")

    with pytest.raises(HTTPException) as same:
        compare_runs(db, run_a.id, run_a.id)
    assert same.value.status_code == 409

    with pytest.raises(HTTPException) as unfinished:
        compare_runs(db, run_a.id, run_b.id)
    assert unfinished.value.status_code == 409
