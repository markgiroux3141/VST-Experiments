import pytest

from varimu.config import (
    ConfigError,
    load_genome_bounds,
    load_sim_settings,
    parse_genome_bounds,
)


def test_repo_sim_settings_load():
    s = load_sim_settings()
    assert s.sample_rate == 96000
    assert isinstance(s.seed, int)


def test_repo_genome_bounds_load_and_every_param_has_a_source():
    params = load_genome_bounds()
    assert "tubes.v6386_a.emission_scale" in params
    assert all(p.source for p in params.values())


def test_tbd_is_allowed_but_unresolved():
    params = parse_genome_bounds({"g": {"p": {"min": "TBD", "max": "TBD", "source": "TBD"}}})
    assert not params["g.p"].resolved


def test_resolved_range_and_choices():
    params = parse_genome_bounds(
        {
            "a": {"min": 0.5, "max": 1, "source": "RCA 6386 datasheet, fig. 2"},
            "b": {"choices": ["x", "y"], "source": "paper"},
        }
    )
    assert params["a"].resolved and params["b"].resolved
    assert params["b"].choices == ("x", "y")


@pytest.mark.parametrize(
    "node,match",
    [
        ({"min": 0, "max": 1}, None),  # no source key -> treated as group
        ({"min": 0, "max": 1, "source": ""}, "source"),
        ({"min": 2, "max": 1, "source": "s"}, r"min \(2\) > max \(1\)"),
        ({"min": "about 3", "max": 4, "source": "s"}, "number or TBD"),
        ({"source": "s"}, "either min/max or choices"),
        ({"min": 0, "max": 1, "choices": ["a"], "source": "s"}, "either min/max or choices"),
        ({"choices": [], "source": "s"}, "non-empty list"),
        ({"min": 0, "max": 1, "source": "s", "typo": 1}, "unknown keys"),
    ],
)
def test_invalid_params_rejected(node, match):
    with pytest.raises(ConfigError, match=match):
        parse_genome_bounds({"p": node})
