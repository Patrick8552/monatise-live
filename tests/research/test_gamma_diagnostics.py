"""Numerical benchmarks are synthetic; none certify a live option or GIL."""
from dataclasses import replace

import pytest

from monatise.application.gold_options import black76, european_greeks
from monatise.research.gamma_diagnostics import diagnose, obstacle_fd, tree_layers
from tests.research.test_phase7 import greek_input


@pytest.mark.parametrize('kind', ['C', 'P'])
@pytest.mark.parametrize('future', [80., 100., 120.])
def test_european_limit_matches_independent_analytic_price_delta_gamma(kind, future):
    args = future, 100., .5, .03, .25, kind
    price = black76(*args)
    greeks = european_greeks(*args)
    pde = obstacle_fd(*args, space=800, steps=1600, american=False)
    tree = tree_layers(*args, steps=1600, american=False)
    assert pde['price'] == pytest.approx(price, abs=.004)
    assert pde['delta'] == pytest.approx(greeks['delta'], abs=.0003)
    assert pde['gamma'] == pytest.approx(greeks['gamma'], rel=.003)
    assert tree['gamma'] == pytest.approx(greeks['gamma'], rel=.003)


@pytest.mark.parametrize('kind', ['C', 'P'])
def test_zero_rate_american_matches_convex_martingale_european_benchmark(kind):
    args = 100., 100., 1., 0., .2, kind
    expected = european_greeks(*args)
    result = obstacle_fd(*args, space=800, steps=1600)
    assert result['price'] == pytest.approx(black76(*args), abs=.002)
    assert result['gamma'] == pytest.approx(expected['gamma'], rel=.002)
    assert result['complementarity_residual'] <= result['algebraic_tolerance']


@pytest.mark.parametrize('kind', ['C', 'P'])
def test_one_day_gamma_requires_a_resolved_diffusion_scale(kind):
    args = 100., 100., 1/365, 0., .2, kind
    expected = european_greeks(*args)
    result = obstacle_fd(*args, space=800, steps=1600)
    assert result['half_width'] == .15
    assert result['gamma'] == pytest.approx(expected['gamma'], rel=.002)
    assert result['price'] == pytest.approx(black76(*args), abs=.0002)


@pytest.mark.parametrize('kind', ['C', 'P'])
def test_positive_rate_american_independent_mesh_time_domain_and_tree_checks(kind):
    args = 100., 100., 1., .01, .2, kind
    coarse = obstacle_fd(*args, space=400, steps=400)
    fine = obstacle_fd(*args, space=800, steps=800)
    time = obstacle_fd(*args, space=800, steps=1600)
    # Same dx and center, farther boundaries: isolates truncation from resolution.
    domain = obstacle_fd(*args, space=1200, steps=800, half_width=2.25)
    tree = tree_layers(*args, steps=1600)
    assert fine['price'] >= black76(*args)
    assert fine['gamma'] > 0
    assert abs(fine['gamma']-time['gamma']) < abs(coarse['gamma']-time['gamma'])
    assert fine['gamma'] == pytest.approx(domain['gamma'], rel=.001)
    assert fine['gamma'] == pytest.approx(tree['gamma'], rel=.002)
    assert fine['complementarity_residual'] <= fine['algebraic_tolerance']


@pytest.mark.parametrize('kind,future', [('C', 140.), ('P', 60.)])
def test_deep_exercise_respects_intrinsic_and_does_not_invent_negative_gamma(kind, future):
    result = obstacle_fd(future, 100., .05, .1, .15, kind)
    intrinsic = max((1 if kind == 'C' else -1)*(future-100), 0)
    assert result['price'] >= intrinsic-1e-8
    assert result['price'] == pytest.approx(intrinsic, abs=.001)
    assert abs(result['gamma']) < 1e-5


@pytest.mark.parametrize('changes', [
    {'space': 101}, {'space': True}, {'steps': 99}, {'space': 1600, 'steps': 3200},
    {'half_width': float('nan')}, {'half_width': True}, {'half_width': .1},
    {'half_width': 7}, {'american': 'yes'},
])
def test_pde_rejects_unbounded_or_unreviewed_configuration(changes):
    with pytest.raises(ValueError):
        obstacle_fd(100., 100., 1., .01, .2, 'C', **changes)


def test_unstable_original_stays_rejected_even_when_diagnostic_methods_agree():
    result = diagnose(greek_input('American'))
    assert result['original']['rejection_reasons'] == ['fine_bump_lattice_gamma_instability']
    assert result['original']['gamma'] is None
    assert result['gamma'] is None
    assert result['numerical_study_status'] == 'EXPERIMENTAL_NOT_CERTIFIED'
    assert not result['production_GIL_compatible'] and not result['gil_enabled']
    assert not result['execution_eligible'] and not result['approval_created']
    assert not result['market_data_quality_certified']
    assert result['errors'] == {}
    assert result['methods']['tree_refinement'][-1]['gamma'] == pytest.approx(
        result['methods']['pde_refinement'][-1]['gamma'], rel=.002)


def test_missing_rate_does_not_become_experimental_iv_or_gamma():
    result = diagnose(replace(greek_input('American'), rate=None))
    assert result['methods'] == {}
    assert result['gamma'] is None
    assert result['errors']['input'] == 'original_model_IV_unavailable'


def test_wrong_exercise_style_cannot_silently_change_models():
    with pytest.raises(ValueError, match='typed_american'):
        diagnose(greek_input('European'))


@pytest.mark.parametrize('steps', [True, 99, 1601])
def test_tree_resource_budget(steps):
    with pytest.raises(ValueError):
        tree_layers(100., 100., 1., .01, .2, 'C', steps=steps)
