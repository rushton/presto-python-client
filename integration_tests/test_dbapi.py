# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, division, print_function

import fixtures
from fixtures import run_presto
import pytest

import presto
from presto.exceptions import PrestoQueryError
from presto.transaction import IsolationLevel


@pytest.fixture
def presto_connection(run_presto):
    _, host, port = run_presto

    yield presto.dbapi.Connection(
        host=host, port=port, user="test", source="test", max_attempts=1
    )


@pytest.fixture
def presto_connection_with_transaction(run_presto):
    _, host, port = run_presto

    yield presto.dbapi.Connection(
        host=host,
        port=port,
        user="test",
        source="test",
        max_attempts=1,
        isolation_level=IsolationLevel.READ_UNCOMMITTED,
    )


def test_select_query(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from system.runtime.nodes")
    rows = cur.fetchall()
    assert len(rows) > 0
    row = rows[0]
    assert row[2] == fixtures.PRESTO_VERSION
    columns = dict([desc[:2] for desc in cur.description])
    assert columns["node_id"] == "varchar"
    assert columns["http_uri"] == "varchar"
    assert columns["node_version"] == "varchar"
    assert columns["coordinator"] == "boolean"
    assert columns["state"] == "varchar"


def test_select_query_result_iteration(presto_connection):
    cur0 = presto_connection.cursor()
    cur0.execute("select custkey from tpch.sf1.customer LIMIT 10")
    rows0 = cur0.genall()

    cur1 = presto_connection.cursor()
    cur1.execute("select custkey from tpch.sf1.customer LIMIT 10")
    rows1 = cur1.fetchall()

    assert len(list(rows0)) == len(rows1)


def test_select_query_result_iteration_statement_params(presto_connection):
    cur = presto_connection.cursor()
    cur.execute(
        """
        select * from (
            values
            (1, 'one', 'a'),
            (2, 'two', 'b'),
            (3, 'three', 'c'),
            (4, 'four', 'd'),
            (5, 'five', 'e')
        ) x (id, name, letter)
        where id >= ?
        """,
        params=(3,)  # expecting all the rows with id >= 3
    )

def test_select_query_result_string_statement_params(presto_connection):
    """
    Tests string parameters in prepared statements
    """
    cur = presto_connection.cursor()
    # test a simple string parameter and
    # a parameter with a quote in it
    cur.execute(
        "select ?",
        params=("six'",),
    )

    rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "six'"


@pytest.mark.parametrize('params', [
    'NOT A LIST OR TUPPLE',
    {'invalid', 'params'},
    object,
])
def test_select_query_invalid_params(presto_connection, params):
    cur = presto_connection.cursor()
    with pytest.raises(AssertionError):
        cur.execute('select ?', params=params)


def test_select_cursor_iteration(presto_connection):
    cur0 = presto_connection.cursor()
    cur0.execute("select nationkey from tpch.sf1.nation")
    rows0 = []
    for row in cur0:
        rows0.append(row)

    cur1 = presto_connection.cursor()
    cur1.execute("select nationkey from tpch.sf1.nation")
    rows1 = cur1.fetchall()

    assert len(rows0) == len(rows1)
    assert sorted(rows0) == sorted(rows1)


def test_select_query_no_result(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from system.runtime.nodes where false")
    rows = cur.fetchall()
    assert len(rows) == 0


def test_select_query_stats(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")

    query_id = cur.stats["queryId"]
    completed_splits = cur.stats["completedSplits"]
    cpu_time_millis = cur.stats["cpuTimeMillis"]
    processed_bytes = cur.stats["processedBytes"]
    processed_rows = cur.stats["processedRows"]
    wall_time_millis = cur.stats["wallTimeMillis"]

    while cur.fetchone() is not None:
        assert query_id == cur.stats["queryId"]
        assert completed_splits <= cur.stats["completedSplits"]
        assert cpu_time_millis <= cur.stats["cpuTimeMillis"]
        assert processed_bytes <= cur.stats["processedBytes"]
        assert processed_rows <= cur.stats["processedRows"]
        assert wall_time_millis <= cur.stats["wallTimeMillis"]

        query_id = cur.stats["queryId"]
        completed_splits = cur.stats["completedSplits"]
        cpu_time_millis = cur.stats["cpuTimeMillis"]
        processed_bytes = cur.stats["processedBytes"]
        processed_rows = cur.stats["processedRows"]
        wall_time_millis = cur.stats["wallTimeMillis"]


def test_select_failed_query(presto_connection):
    cur = presto_connection.cursor()
    with pytest.raises(presto.exceptions.PrestoUserError):
        cur.execute("select * from catalog.schema.do_not_exist")
        cur.fetchall()


def test_select_tpch_1000(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
    rows = cur.fetchall()
    assert len(rows) == 1000


def test_cancel_query(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from tpch.sf1.customer")
    cur.fetchone()  # TODO (https://github.com/prestosql/presto/issues/2683) test with and without .fetchone
    cur.cancel()  # would raise an exception if cancel fails

    cur = presto_connection.cursor()
    with pytest.raises(Exception) as cancel_error:
        cur.cancel()
    assert "Cancel query failed; no running query" in str(cancel_error.value)


def test_session_properties(run_presto):
    _, host, port = run_presto

    connection = presto.dbapi.Connection(
        host=host,
        port=port,
        user="test",
        source="test",
        session_properties={"query_max_run_time": "10m", "query_priority": "1"},
        max_attempts=1,
    )
    cur = connection.cursor()
    cur.execute("SHOW SESSION")
    rows = cur.fetchall()
    assert len(rows) > 2
    for prop, value, _, _, _ in rows:
        if prop == "query_max_run_time":
            assert value == "10m"
        elif prop == "query_priority":
            assert value == "1"


def test_transaction_single(presto_connection_with_transaction):
    connection = presto_connection_with_transaction
    for _ in range(3):
        cur = connection.cursor()
        cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows = cur.fetchall()
        connection.commit()
        assert len(rows) == 1000


def test_transaction_rollback(presto_connection_with_transaction):
    connection = presto_connection_with_transaction
    for _ in range(3):
        cur = connection.cursor()
        cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows = cur.fetchall()
        connection.rollback()
        assert len(rows) == 1000


def test_transaction_multiple(presto_connection_with_transaction):
    with presto_connection_with_transaction as connection:
        cur1 = connection.cursor()
        cur1.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows1 = cur1.fetchall()

        cur2 = connection.cursor()
        cur2.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows2 = cur2.fetchall()

    assert len(rows1) == 1000
    assert len(rows2) == 1000

def test_invalid_query_throws_correct_error(presto_connection):
    """
    tests that an invalid query raises the correct exception
    """
    cur = presto_connection.cursor()
    with pytest.raises(PrestoQueryError):
        cur.execute(
            """
            select * FRMO foo WHERE x = ?; 
            """,
            params=(3,),
        )
