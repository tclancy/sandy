import textwrap
from sandy.pipeline import run_pipeline


def _make_plugins(tmp_path, plugins):
    for filename, code in plugins.items():
        (tmp_path / filename).write_text(textwrap.dedent(code))
    return str(tmp_path)


def test_run_pipeline_returns_results(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": f"echo: {text}"}
        """
        },
    )
    results, errors = run_pipeline("echo this", "tom", plugin_dir=plugin_dir)
    assert len(results) == 1
    assert results[0][0] == "echo"
    assert results[0][1]["text"] == "echo: echo this"
    assert errors == []


def test_run_pipeline_no_matches(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "echo.py": """
            name = "echo"
            commands = ["echo"]
            def handle(text, actor):
                return {"text": "ok"}
        """
        },
    )
    results, errors = run_pipeline("unknown", "tom", plugin_dir=plugin_dir)
    assert results == []
    assert errors == []


def test_run_pipeline_partial_failure(tmp_path):
    plugin_dir = _make_plugins(
        tmp_path,
        {
            "alpha.py": """
            name = "alpha"
            commands = ["test"]
            def handle(text, actor):
                raise RuntimeError("kaboom")
        """,
            "beta.py": """
            name = "beta"
            commands = ["test"]
            def handle(text, actor):
                return {"text": "beta worked"}
        """,
        },
    )
    results, errors = run_pipeline("test", "tom", plugin_dir=plugin_dir)
    assert len(results) == 1
    assert results[0][0] == "beta"
    assert len(errors) == 1
    assert "alpha" in errors[0]
