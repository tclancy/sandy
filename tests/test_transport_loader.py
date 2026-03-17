import textwrap
from sandy.transport_loader import load_transports


def _make_transport(tmp_path, filename, code):
    (tmp_path / filename).write_text(textwrap.dedent(code))
    return str(tmp_path)


def test_load_valid_transport(tmp_path):
    _make_transport(
        tmp_path,
        "test_channel.py",
        """
        name = "test_channel"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return response["text"]
    """,
    )
    transports = load_transports(str(tmp_path))
    assert len(transports) == 1
    assert transports[0].name == "test_channel"


def test_skip_malformed_transport(tmp_path, capsys):
    _make_transport(
        tmp_path,
        "bad.py",
        """
        name = "bad"
        # missing listen and format_response
    """,
    )
    transports = load_transports(str(tmp_path))
    assert transports == []
    assert "missing" in capsys.readouterr().err.lower()


def test_skip_inactive_transport(tmp_path):
    _make_transport(
        tmp_path,
        "disabled.py",
        """
        name = "disabled"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    config = {"daemon": {"transports": ["other"]}}
    transports = load_transports(str(tmp_path), config=config)
    assert transports == []


def test_load_only_active_transports(tmp_path):
    _make_transport(
        tmp_path,
        "alpha.py",
        """
        name = "alpha"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    _make_transport(
        tmp_path,
        "beta.py",
        """
        name = "beta"
        async def listen(callback):
            pass
        def format_response(plugin_name, response):
            return ""
    """,
    )
    config = {"daemon": {"transports": ["alpha"]}}
    transports = load_transports(str(tmp_path), config=config)
    assert len(transports) == 1
    assert transports[0].name == "alpha"
