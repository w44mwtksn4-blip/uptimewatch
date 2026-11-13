"""Config validation."""

import pytest

from uptimewatch.config import ConfigError, load_config, parse_config


def valid():
    return {
        "interval": 30,
        "timeout": 5,
        "failure_threshold": 2,
        "checks": [
            {"name": "Web", "type": "http", "url": "https://example.com", "expected_status": 204},
            {
                "name": "SSH",
                "type": "tcp",
                "host": "example.com",
                "port": 22,
                "failure_threshold": 5,
            },
        ],
    }


def test_valid_config_is_parsed():
    settings = parse_config(valid())
    assert settings.interval == 30
    assert settings.timeout == 5
    web, ssh = settings.checks
    assert web.expected_status == 204 and web.failure_threshold == 2
    assert ssh.target == "example.com:22" and ssh.failure_threshold == 5


def test_defaults_are_applied():
    settings = parse_config({"checks": [{"name": "A", "type": "tcp", "host": "h", "port": 1}]})
    assert (settings.interval, settings.timeout, settings.failure_threshold) == (60.0, 10.0, 3)


def test_example_config_is_valid(tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    assert len(load_config(example).checks) == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(checks=[]),
        lambda c: c.pop("checks"),
        lambda c: c.update(interval=0),
        lambda c: c.update(timeout=-1),
        lambda c: c.update(failure_threshold=0),
        lambda c: c.update(failure_threshold=True),
        lambda c: c.update(unknown_option=1),
        lambda c: c["checks"][0].update(url="example.com"),
        lambda c: c["checks"][0].update(url="ftp://example.com"),
        lambda c: c["checks"][0].update(expected_status=99),
        lambda c: c["checks"][0].update(expected_stauts=200),
        lambda c: c["checks"][0].update(type="ping"),
        lambda c: c["checks"][0].update(name=""),
        lambda c: c["checks"][1].update(port=70000),
        lambda c: c["checks"][1].update(port="22"),
        lambda c: c["checks"][1].pop("host"),
        lambda c: c["checks"][1].update(name="Web"),  # duplicate name
    ],
)
def test_invalid_configs_are_rejected(mutate):
    config = valid()
    mutate(config)
    with pytest.raises(ConfigError):
        parse_config(config)


def test_non_mapping_config_is_rejected():
    with pytest.raises(ConfigError):
        parse_config(["not", "a", "mapping"])


def test_missing_and_malformed_files_raise_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("checks: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad)
