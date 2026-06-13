"""
pytest 전역 설정.

Django settings 는 import 시점에 환경변수(SECRET_KEY 등)를 요구하고
MongoDB 연결을 등록하므로, 테스트용 기본값을 settings import 이전에 주입한다.
또한 mongoengine 을 mongomock(in-memory)로 바꿔 실제 MongoDB 없이 테스트한다.
"""
import os

# --- settings import 이전에 테스트용 환경변수 주입 ---
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/complaints_db")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("KAKAO_MAP_API_KEY", "test-kakao-key")

import pytest


@pytest.fixture(autouse=True)
def mongomock_connection():
    """각 테스트마다 mongoengine 을 mongomock(in-memory)로 격리한다."""
    import mongoengine
    import mongomock

    mongoengine.disconnect(alias="default")
    mongoengine.connect(
        "complaints_db",
        alias="default",
        mongo_client_class=mongomock.MongoClient,
        uuidRepresentation="standard",
    )
    yield
    mongoengine.disconnect(alias="default")
