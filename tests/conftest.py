from collections.abc import Iterator

import pytest
from hypothesis import settings

from tests.harness import FakeUnit, Stack, run_api

# 1 つの入力が 2 つのプロセスを跨ぐ HTTP の往復で、並列実行の負荷による遅れを入力ごとの失敗にしないため deadline を外す。
settings.register_profile("e2e", deadline=None)
settings.load_profile("e2e")


@pytest.fixture(scope="session")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """
    fake の空気清浄機と、それに接続した API サーバー (xdist の worker ごとに 1 組)。

    状態を共有するので、各テストと property の各入力は最初に `stack.unit.reset()` を呼ぶ。
    """
    log_path = tmp_path_factory.mktemp("api") / "uvicorn.log"
    with (
        FakeUnit.serve() as unit,
        run_api(env={"DAIKIN_HOST": unit.url}, log_path=log_path) as api,
    ):
        yield Stack(unit, api)
