import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Generator

from src.models.po import Base


@pytest.fixture(scope="session")
def test_db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    Session = sessionmaker(bind=test_db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_symbol():
    return "SHFE.rb2505"


@pytest.fixture
def sample_account_id():
    return "test_account_001"
