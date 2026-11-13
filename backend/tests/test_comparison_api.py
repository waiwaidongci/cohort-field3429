import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.database import Base, get_db
from src.models import Customer, Dataset, Segment, SegmentRun, User
from src.routes.segments import router
from src.utils.auth import current_user


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    def override_db():
        with session() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = lambda: User(email="viewer@weian.demo", name="林禾", role="viewer", password_hash="")

    with session() as db:
        dataset = Dataset(name="d", source_file="d.csv")
        db.add(dataset)
        db.flush()
        customers = []
        for i in range(4):
            customer = Customer(dataset_id=dataset.id, code=f"WA-{i:04d}", recency=10, frequency=5, spend=500, learning_days=5)
            db.add(customer)
            customers.append(customer)
        db.flush()
        run_a = SegmentRun(name="a", dataset_id=dataset.id, features=["recency", "spend"], k_min=2, k_max=2, status="completed")
        run_b = SegmentRun(name="b", dataset_id=dataset.id, features=["recency", "spend"], k_min=2, k_max=2, status="completed")
        queued = SegmentRun(name="c", dataset_id=dataset.id, features=["recency", "spend"], k_min=2, k_max=2, status="queued")
        db.add_all([run_a, run_b, queued])
        db.flush()
        for run, groups in ((run_a, ((0, [0, 1]), (1, [2, 3]))), (run_b, ((0, [2, 3]), (1, [0, 1])))):
            for label, indexes in groups:
                db.add(Segment(run_id=run.id, label=label, name=f"群{label}", size=2, center={"recency": 10, "spend": 500},
                               customer_ids=[customers[index].id for index in indexes], recommendation=""))
        db.commit()
        ids = {"a": run_a.id, "b": run_b.id, "queued": queued.id}

    with TestClient(app) as test_client:
        yield test_client, ids


def test_viewer_can_compare_and_sees_renumbering_not_churn(client):
    test_client, ids = client
    response = test_client.get("/segments/compare", params={"run_a": ids["a"], "run_b": ids["b"]})
    assert response.status_code == 200
    body = response.json()
    assert body["comparable"] is True
    assert body["summary"]["common"] == 4
    assert body["summary"]["migrated"] == 0
    assert body["summary"]["retained"] == 4
    assert body["summary"]["reconciled"] is True
    assert body["added_codes"] == [] and body["left_codes"] == []
    assert sum(1 for m in body["matches"] if m["label_changed"]) == 2
    # 已经存在的群组接口保持原样
    assert test_client.get("/segments", params={"run_id": ids["a"]}).status_code == 200


def test_comparison_rejects_bad_requests(client):
    test_client, ids = client
    same = test_client.get("/segments/compare", params={"run_a": ids["a"], "run_b": ids["a"]})
    assert same.status_code == 409
    missing = test_client.get("/segments/compare", params={"run_a": ids["a"], "run_b": 9999})
    assert missing.status_code == 404
    unfinished = test_client.get("/segments/compare", params={"run_a": ids["a"], "run_b": ids["queued"]})
    assert unfinished.status_code == 409
    assert "尚未完成" in unfinished.json()["detail"]
