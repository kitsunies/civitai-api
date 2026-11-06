import json

from civitai_api import cli

from .fake import LOCATION, fake_upstream


def use_fake(monkeypatch):
    monkeypatch.setattr(cli, "Upstream", lambda: fake_upstream())


def test_search_text(monkeypatch, capsys):
    use_fake(monkeypatch)
    assert cli.main(["search", "pony", "-s", "civitai.red", "-t", "checkpoint"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("257749  checkpoint  Pony  Pony Diffusion V6 XL  1.1m downloads")
    assert "--cursor '63212|1266322|43331'" in err


def test_json_and_download(monkeypatch, capsys):
    use_fake(monkeypatch)
    assert cli.main(["version", "290640", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["creator"] == "PurpleSmartAI"
    assert cli.main(["download", "290640"]) == 0
    assert capsys.readouterr().out.strip() == LOCATION
    assert cli.main(["model", "257749"]) == 0 and "versions:" in capsys.readouterr().out


def test_exit_codes(monkeypatch, capsys):
    use_fake(monkeypatch)
    assert cli.main(["model", "999"]) == 2
    assert cli.main(["model", "451"]) == 1
    assert "error:" in capsys.readouterr().err
