import logging

import pytest as pytest

from .conftest import raises


@pytest.fixture
def dbutils(config):
    from databricks.sdk.dbutils import RemoteDbUtils
    return RemoteDbUtils(config)


def test_fs_cp(dbutils, mocker):
    inner = mocker.patch('databricks.sdk.mixins.dbfs.DbfsExt.copy')

    dbutils.fs.cp('a', 'b', recurse=True)

    inner.assert_called_with('a', 'b', recursive=True)


def test_fs_head(dbutils, mocker):
    from databricks.sdk.service.dbfs import ReadResponse
    inner = mocker.patch('databricks.sdk.service.dbfs.DbfsAPI.read',
                         return_value=ReadResponse(data='aGVsbG8='))

    result = dbutils.fs.head('a')

    inner.assert_called_with('a', length=65536, offset=0)
    assert result == 'hello'


def test_fs_ls(dbutils, mocker):
    from databricks.sdk.service.dbfs import FileInfo
    inner = mocker.patch('databricks.sdk.mixins.dbfs.DbfsExt.list',
                         return_value=[
                             FileInfo(path='b', file_size=10, modification_time=20),
                             FileInfo(path='c', file_size=30, modification_time=40),
                         ])

    result = dbutils.fs.ls('a')

    from databricks.sdk.dbutils import FileInfo
    inner.assert_called_with('a')
    assert len(result) == 2
    assert result[0] == FileInfo('dbfs:b', 'b', 10, 20)


def test_fs_mkdirs(dbutils, mocker):
    inner = mocker.patch('databricks.sdk.service.dbfs.DbfsAPI.mkdirs')

    dbutils.fs.mkdirs('a')

    inner.assert_called_with('a')


def test_fs_mv(dbutils, mocker):
    inner = mocker.patch('databricks.sdk.mixins.dbfs.DbfsExt.move_')

    dbutils.fs.mv('a', 'b')

    inner.assert_called_with('a', 'b', recursive=False, overwrite=True)


def test_fs_put(dbutils, mocker):
    inner = mocker.patch('databricks.sdk.service.dbfs.DbfsAPI.put')

    dbutils.fs.put('a', 'b')

    inner.assert_called_with('a', contents='b', overwrite=False)


def test_fs_rm(dbutils, mocker):
    inner = mocker.patch('databricks.sdk.service.dbfs.DbfsAPI.delete')

    dbutils.fs.rm('a')

    inner.assert_called_with('a', recursive=False)


@raises('cluster_id is required in the configuration. Config: host=http://localhost, auth_type=noop')
def test_fs_mount_without_cluster_fails(dbutils):
    dbutils.fs.mount('s3://foo', 'bar')


@pytest.fixture
def dbutils_proxy(mocker):
    from databricks.sdk.core import Config
    from databricks.sdk.dbutils import RemoteDbUtils
    from databricks.sdk.service._internal import Wait
    from databricks.sdk.service.clusters import ClusterInfo, State
    from databricks.sdk.service.commands import (CommandStatus,
                                                 CommandStatusResponse,
                                                 Created, Language, Results)

    from .conftest import noop_credentials

    cluster_get = mocker.patch('databricks.sdk.service.clusters.ClustersAPI.get',
                               return_value=ClusterInfo(state=State.RUNNING))
    context_create = mocker.patch('databricks.sdk.service.commands.CommandExecutionAPI.create',
                                  return_value=Wait(lambda **kwargs: Created('y')))

    def inner(results_data: any, expect_command: str):
        import json
        command_execute = mocker.patch(
            'databricks.sdk.service.commands.CommandExecutionAPI.execute',
            return_value=Wait(lambda **kwargs: CommandStatusResponse(
                results=Results(data=json.dumps(results_data)), status=CommandStatus.Finished)))

        def assertions():
            cluster_get.assert_called_with('x')
            context_create.assert_called_with(cluster_id='x', language=Language.python)
            command_execute.assert_called_with(cluster_id='x',
                                               context_id='y',
                                               language=Language.python,
                                               command=expect_command)

        dbutils = RemoteDbUtils(
            Config(host='http://localhost', cluster_id='x', credentials_provider=noop_credentials))
        return dbutils, assertions

    return inner


def test_fs_mount(dbutils_proxy):
    command = ('\n'
               '        import json\n'
               '        (args, kwargs) = json.loads(\'[[], {"source": "s3://foo", '
               '"mountPoint": "bar", "encryptionType": "", "owner": "", '
               '"extraConfigs": null}]\')\n'
               '        result = dbutils.fs.mount(*args, **kwargs)\n'
               '        dbutils.notebook.exit(json.dumps(result))\n'
               '        ')
    dbutils, assertions = dbutils_proxy({}, command)

    dbutils.fs.mount('s3://foo', 'bar')

    assertions()


def test_fs_update_mount(dbutils_proxy):
    command = ('\n'
               '        import json\n'
               '        (args, kwargs) = json.loads(\'[[], {"source": '
               '"s3://foo2", "mountPoint": "bar", "encryptionType": "", "owner": '
               '"", "extraConfigs": null}]\')\n'
               '        result = dbutils.fs.updateMount(*args, **kwargs)\n'
               '        dbutils.notebook.exit(json.dumps(result))\n'
               '        ')
    dbutils, assertions = dbutils_proxy({}, command)

    dbutils.fs.updateMount('s3://foo2', 'bar')

    assertions()


def test_fs_mounts(dbutils_proxy):
    command = ('\n'
               '        import json\n'
               "        (args, kwargs) = json.loads('[[], {}]')\n"
               '        result = dbutils.fs.mounts(*args, **kwargs)\n'
               '        dbutils.notebook.exit(json.dumps(result))\n'
               '        ')
    dbutils, assertions = dbutils_proxy([('a', 'b', 'c'), ('d', 'e', 'f'), ], command)

    mounts = dbutils.fs.mounts()

    assert len(mounts) == 2
    assert mounts[0].mountPoint == 'a'
    assert mounts[0].source == 'b'

    assertions()


def test_any_proxy(dbutils_proxy):
    command = ('\n'
               '        import json\n'
               '        (args, kwargs) = json.loads(\'[["a"], {}]\')\n'
               '        result = dbutils.widgets.getParameter(*args, **kwargs)\n'
               '        dbutils.notebook.exit(json.dumps(result))\n'
               '        ')
    dbutils, assertions = dbutils_proxy('b', command)

    param = dbutils.widgets.getParameter('a')

    assert param == 'b'

    assertions()


def test_secrets_get_and_redacting_logs(dbutils, mocker, caplog):
    inner = mocker.patch('databricks.sdk.core.ApiClient.do', return_value={'value': 'aGVsbG8='})

    value = dbutils.secrets.get('foo', 'bar')
    logging.info(f'Secret is {value}')

    inner.assert_called_with('GET', '/api/2.0/secrets/get', query={'key': 'bar', 'scope': 'foo'})

    assert value == 'hello'
    assert 'Secret is [REDACTED]' in caplog.text