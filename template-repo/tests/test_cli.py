import pytest

from {{PACKAGE}} import __version__
from {{PACKAGE}}.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_arguments():
    assert main([]) == 0
