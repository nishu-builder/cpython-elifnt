import subprocess
import sys
import os
from typing import Any, NoReturn

from test import support
from test.support import os_helper

from .setup import setup_process, setup_test_dir
from .runtests import RunTests, JsonFile, JsonFileType
from .single import run_single_test
from .utils import (
    StrPath, StrJSON, TestFilter,
    get_temp_dir, get_work_dir, exit_timeout)


USE_PROCESS_GROUP = (hasattr(os, "setsid") and hasattr(os, "killpg"))


def create_worker_process(runtests: RunTests, output_fd: int,
                          tmp_dir: StrPath | None = None) -> subprocess.Popen:
    python_cmd = runtests.python_cmd
    worker_json = runtests.as_json()

    python_opts = support.args_from_interpreter_flags()
    if python_cmd is not None:
        executable = python_cmd
        # Remove -E option, since --python=COMMAND can set PYTHON environment
        # variables, such as PYTHONPATH, in the worker process.
        python_opts = [opt for opt in python_opts if opt != "-E"]
    else:
        executable = (sys.executable,)
    cmd = [*executable, *python_opts,
           '-u',    # Unbuffered stdout and stderr
           '-m', 'test.libregrtest.worker',
           worker_json]

    env = dict(os.environ)
    if tmp_dir is not None:
        env['TMPDIR'] = tmp_dir
        env['TEMP'] = tmp_dir
        env['TMP'] = tmp_dir

    # Running the child from the same working directory as regrtest's original
    # invocation ensures that TEMPDIR for the child is the same when
    # sysconfig.is_python_build() is true. See issue 15300.
    #
    # Emscripten and WASI Python must start in the Python source code directory
    # to get 'python.js' or 'python.wasm' file. Then worker_process() changes
    # to a temporary directory created to run tests.
    work_dir = os_helper.SAVEDCWD

    kwargs: dict[str, Any] = dict(
        env=env,
        stdout=output_fd,
        # bpo-45410: Write stderr into stdout to keep messages order
        stderr=output_fd,
        text=True,
        close_fds=True,
        cwd=work_dir,
    )
    if USE_PROCESS_GROUP:
        kwargs['start_new_session'] = True

    # Pass json_file to the worker process
    json_file = runtests.json_file
    json_file.configure_subprocess(kwargs)

    with json_file.inherit_subprocess():
        return subprocess.Popen(cmd, **kwargs)


def worker_process(worker_json: StrJSON) -> NoReturn:
    runtests = RunTests.from_json(worker_json)
    test_name = runtests.tests[0]
    match_tests: TestFilter = runtests.match_tests
    json_file: JsonFile = runtests.json_file

    setup_test_dir(runtests.test_dir)
    setup_process()

    if runtests.rerun:
        if match_tests:
            matching = "matching: " + ", ".join(pattern for pattern, result in match_tests if result)
            print(f"Re-running {test_name} in verbose mode ({matching})", flush=True)
        else:
            print(f"Re-running {test_name} in verbose mode", flush=True)

    result = run_single_test(test_name, runtests)

    if json_file.file_type == JsonFileType.STDOUT:
        print()
        result.write_json_into(sys.stdout)
    else:
        with json_file.open('w', encoding='utf-8') as json_fp:
            result.write_json_into(json_fp)

    sys.exit(0)


def main():
    if len(sys.argv) != 2:
        print("usage: python -m test.libregrtest.worker JSON")
        sys.exit(1)
    worker_json = sys.argv[1]

    tmp_dir = get_temp_dir()
    work_dir = get_work_dir(tmp_dir, worker=True)

    with exit_timeout():
        with os_helper.temp_cwd(work_dir, quiet=True):
            worker_process(worker_json)


if __name__ == "__main__":
    main()
