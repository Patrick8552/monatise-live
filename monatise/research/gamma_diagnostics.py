"""Offline American futures-option numerical experiments, never eligible Greeks.

Two diagnostic estimators avoid second differences of a piecewise-linear root
tree price: CRR layer slopes and a fixed log-grid implicit obstacle problem.
Neither replaces phase7.greeks.validated or registers with options/GIL engines.
Only prices, delta and gamma are studied here; vega/theta and market-data quality
still require separate validation. No IO, provider construction or new dependency.
"""
from math import exp, isfinite, log, sqrt

from monatise.application.gold_options import _inputs
from monatise.research.institutional.models import digest
from monatise.research.institutional.phase7.greeks import GreekInput, validated


def _check(future, strike, years, rate, volatility, kind):
    _inputs(future, strike, years, rate, volatility, kind)
    if any(type(v) not in (float, int) for v in (future, strike, years, rate, volatility)):
        raise ValueError('finite_scalar_numerical_inputs_required')


def tree_layers(future, strike, years, rate, volatility, kind, *, steps=800, american=True):
    """Futures-martingale CRR; differentiate layer 1/2 slopes on the same tree.

    This is a finite-step estimator, evaluated at later tree layers. Independent
    step refinement and PDE comparison are necessary; no exact-time claim.
    """
    _check(future, strike, years, rate, volatility, kind)
    if type(steps) is not int or not 100 <= steps <= 1600 or type(american) is not bool:
        raise ValueError('bounded_tree_steps_and_exercise_style_required')
    dt = years / steps
    jump = volatility * sqrt(dt)
    up, down = exp(jump), exp(-jump)
    probability = (1 - down) / (up - down)
    if not 0 < probability < 1:
        raise ValueError('futures_martingale_probability_invalid')
    discount = exp(-rate * dt)
    sign = 1 if kind == 'C' else -1
    nodes = [max(0., sign * (future * exp((2*j - steps)*jump) - strike))
             for j in range(steps + 1)]
    for n in range(steps - 1, -1, -1):
        values = [discount * (probability*nodes[j+1] + (1-probability)*nodes[j])
                  for j in range(n+1)]
        if american:
            values = [max(sign*(future*exp((2*j-n)*jump)-strike), values[j])
                      for j in range(n+1)]
        nodes = values
        if n == 2:
            layer2 = nodes[:]
        if n == 1:
            layer1 = nodes[:]
    lower_delta = (layer2[1]-layer2[0]) / (future-future*down*down)
    upper_delta = (layer2[2]-layer2[1]) / (future*up*up-future)
    result = dict(price=nodes[0], delta=(layer1[1]-layer1[0])/(future*up-future*down),
                  gamma=(upper_delta-lower_delta)/(.5*future*(up*up-down*down)))
    if any(not isfinite(v) for v in result.values()):
        raise ValueError('nonfinite_tree_diagnostic')
    return dict(**result, steps=steps, american=american, method='CRR_LAYER_SLOPES')


def _tridiagonal(lower, diagonal, upper, rhs):
    size = len(diagonal)
    cp, dp = [0.]*size, [0.]*size
    for j in range(size):
        pivot = diagonal[j] - (lower[j]*cp[j-1] if j else 0)
        if not isfinite(pivot) or pivot <= 0:
            raise ValueError('obstacle_linear_solve_invalid_pivot')
        cp[j] = upper[j]/pivot
        dp[j] = (rhs[j] - (lower[j]*dp[j-1] if j else 0))/pivot
    values = [0.]*size
    values[-1] = dp[-1]
    for j in range(size-2, -1, -1):
        values[j] = dp[j] - cp[j]*values[j+1]
    return values


def obstacle_fd(future, strike, years, rate, volatility, kind, *, space=400,
                steps=400, half_width=None, american=True):
    """Implicit Euler in log futures with policy iteration of each discrete LCP.

    L = sigma^2/2 * (d_xx - d_x) - r: the futures drift is zero.
    This solves the discrete complementarity problem, unlike a single projection
    of the unconstrained time step. Gamma=(V_xx-V_x)/F^2 at the fixed center node.
    Domain edges use deep intrinsic/discounted payoff approximations; truncation
    is not proved by an LCP residual, so review domain and space/time separately.
    """
    _check(future, strike, years, rate, volatility, kind)
    if (type(space) is not int or not 100 <= space <= 1600 or space % 2
            or type(steps) is not int or not 100 <= steps <= 3200
            or space*steps > 2_560_000 or type(american) is not bool):
        raise ValueError('bounded_even_mesh_and_time_budget_required')
    # Concentrate the fixed grid for short maturities instead of resolving an
    # unnecessarily wide domain with few nodes across the diffusion scale.
    minimum_width = max(.15, abs(log(strike/future))+.1, 7.5*volatility*sqrt(years))
    width = minimum_width if half_width is None else half_width
    if (type(width) not in (int, float) or not isfinite(width)
            or not minimum_width <= width <= 6):
        raise ValueError('reviewed_bounded_domain_must_cover_strike_and_tails')
    dx, dt = 2*width/space, years/steps
    sign = 1 if kind == 'C' else -1
    grid = [future*exp((j-space//2)*dx) for j in range(space+1)]
    payoff = [max(sign*(p-strike), 0) for p in grid]
    values, size = payoff[:], space-1
    left_rate = .5*volatility**2/dx**2 + .25*volatility**2/dx
    right_rate = .5*volatility**2/dx**2 - .25*volatility**2/dx
    if min(left_rate, right_rate) < 0:
        raise ValueError('nonmonotone_spatial_operator')
    lower = [-dt*left_rate]*size
    diagonal = [1+dt*(left_rate+right_rate+rate)]*size
    upper = [-dt*right_rate]*size
    # Fixed algebraic solve tolerance, unrelated to market or Greek admission.
    tolerance = 1e-10*max(future, strike)
    max_residual, max_iterations = 0., 0
    for step in range(1, steps+1):
        discount = exp(-rate*step*dt)
        left, right = payoff[0]*discount, payoff[-1]*discount
        if american:
            left, right = max(left, payoff[0]), max(right, payoff[-1])
        rhs = values[1:-1]
        rhs[0] -= lower[0]*left
        rhs[-1] -= upper[-1]*right
        if american:
            guess, previous = values[1:-1], None
            for iteration in range(50):
                residuals = [diagonal[j]*guess[j]
                    + (lower[j]*guess[j-1] if j else 0)
                    + (upper[j]*guess[j+1] if j+1 < size else 0) - rhs[j]
                    for j in range(size)]
                gaps = [guess[j]-payoff[j+1] for j in range(size)]
                residual = max(max(0, -gaps[j], -residuals[j],
                                   abs(min(gaps[j], residuals[j]))) for j in range(size))
                if not isfinite(residual):
                    raise ValueError('nonfinite_complementarity_residual')
                if residual <= tolerance:
                    break
                active = [gaps[j] <= residuals[j] for j in range(size)]
                if active == previous:
                    raise ValueError('obstacle_policy_stalled_above_tolerance')
                guess = _tridiagonal(
                    [0 if active[j] else lower[j] for j in range(size)],
                    [1 if active[j] else diagonal[j] for j in range(size)],
                    [0 if active[j] else upper[j] for j in range(size)],
                    [payoff[j+1] if active[j] else rhs[j] for j in range(size)])
                previous = active
            else:
                raise ValueError('obstacle_policy_iteration_budget_exhausted')
            max_residual = max(max_residual, residual)
            max_iterations = max(max_iterations, iteration)
            interior = guess
        else:
            interior = _tridiagonal(lower, diagonal, upper, rhs)
        values = [left]+interior+[right]
    center = space//2
    vx = (values[center+1]-values[center-1])/(2*dx)
    vxx = (values[center+1]-2*values[center]+values[center-1])/dx**2
    result = dict(price=values[center], delta=vx/future, gamma=(vxx-vx)/future**2)
    if any(not isfinite(v) for v in result.values()):
        raise ValueError('nonfinite_obstacle_diagnostic')
    return dict(**result, space=space, steps=steps, half_width=width, american=american,
                complementarity_residual=max_residual, algebraic_tolerance=tolerance,
                max_policy_iterations=max_iterations, method='LOG_IMPLICIT_EULER_POLICY_ITERATION')


def diagnose(x):
    """Reproduce the unchanged validator then compare bounded experimental methods.

    Agreement is a diagnostic, never a substitute for the original rejection.
    No gate tolerance is changed and no eligible gamma is returned.
    """
    if not isinstance(x, GreekInput) or x.style != 'American':
        raise ValueError('typed_american_model_input_required')
    original = validated(x)
    result = dict(version='american-gamma-diagnostic-v1', input_sha256=digest(x),
        original=original, numerical_study_status='EXPERIMENTAL_NOT_CERTIFIED',
        gamma=None, production_GIL_compatible=False, research_only=True,
        execution_eligible=False, gil_enabled=False, approval_created=False,
        orders_placed=0, production_registered=False,
        market_data_quality_certified=False, methods={}, errors={})
    if original['iv'] is None:
        result['errors']['input'] = 'original_model_IV_unavailable'
        result['reproducibility_sha256'] = digest(result)
        return result
    args = (x.future, x.strike, x.years, x.rate, original['iv'], x.kind)
    for name, run in (
        ('tree_refinement', lambda: [tree_layers(*args, steps=n) for n in (400, 800, 1600)]),
        ('pde_refinement', lambda: [obstacle_fd(*args, space=n, steps=n) for n in (200, 400, 800)]),
        ('pde_time_refinement', lambda: obstacle_fd(*args, space=800, steps=1600))):
        try:
            result['methods'][name] = run()
        except (ValueError, TypeError, ArithmeticError) as exc:
            result['errors'][name] = str(exc)
    result['reproducibility_sha256'] = digest(result)
    return result
