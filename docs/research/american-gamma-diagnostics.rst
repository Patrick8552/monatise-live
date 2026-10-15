American futures-option gamma investigation
===========================================

This is a separate offline numerical research track based on Phase 10 commit
58ea23471824d760834826a54434c556640d1809. It adds no provider connection,
production registration, deployment, order or subscription. The live collector,
calibration windows, frozen H1 and its two-hour lifetime, existing Greek
validator and trade/GIL rules are unchanged. No new dependency is required.

Reproduced failure and interpretation
-------------------------------------

The existing American test input and an already licensed genuine archived GC
option/underlying quote pair both reproduce
``fine_bump_lattice_gamma_instability``. An IV solution and plausible prices do
not establish gamma convergence. The existing research admission path still
rejects these cases, leaving gamma null. The known failing regression remains.

At a fixed finite CRR resolution, option value as a function of the root futures
price is piecewise linear between payoff/exercise breakpoints. Shrinking a price
bump without resolving the tree can land within a segment or across different
kinks. Odd/even averaging does not remove this problem. A second difference of
such root prices can vary substantially while prices themselves agree closely.
The observations support this mechanism; they are not an exhaustive proof of all
American-option sensitivity errors.

Independent diagnostic estimators
----------------------------------

``monatise.research.gamma_diagnostics.tree_layers`` takes delta from layer-one
slopes and gamma from the difference between layer-two slopes. The futures
transition probability is chosen so the futures price is a martingale; discount
is applied separately. This is still an approximation at later tree times, so
400/800/1600-step refinement and an independent method comparison are retained.

``obstacle_fd`` solves a different discretization: implicit Euler on a fixed log
futures grid, with policy iteration for the discrete American complementarity
problem at every time step. It checks both obstacle/continuation feasibility and
complementarity residual, with a fixed algebraic tolerance. This is stronger than
solving an unconstrained time step followed by one payoff projection. Delta and
gamma come from fixed neighboring grid nodes, including the log-coordinate
chain rule; they are not bumps of a linearly interpolated price.

The study uses separate space/time refinements and farther domain boundaries at
the same spatial resolution. Algebraic residual is not discretization error.
Finite-domain edges use deep intrinsic/discounted-payoff approximations; domain
review is essential. Configuration and iteration budgets reject unsupported or
unconverged problems. No tolerance was selected by observing market holdouts.
The fixed domain depends on volatility/time diffusion scale and distance to the
strike. The initial wide-domain study inadequately resolved one-day and tail
cases; its four review flags are preserved in private evidence. The subsequent
diffusion-scaled grid retains every declared comparison case.

``diagnose(GreekInput)`` first invokes the unchanged validator. It retains that
original result, records bounded alternative estimates and always returns null
eligible gamma, ``EXPERIMENTAL_NOT_CERTIFIED``, and false GIL/execution flags.
It does not establish native quote quality, correct rates, chain coverage or
positioning. Passing a numerical study cannot override a market-data rejection.

Verification and limits
------------------------

Synthetic tests cover independent Black-76 European limits for calls/puts and
different moneyness, the zero-rate American convex-martingale limit, positive-rate
American comparisons, deep exercise, separate time/mesh/domain checks, solver
budgets and preservation of the known original rejection. These test benchmarks
do not certify a real quote or an exchange model.

The genuine replay reads only previously sealed private native journals and
dated rate evidence, independently verifies their hashes/DBN bytes, and retains
the original model-input provenance. It does not acquire a new live options feed.
Raw/licensed inputs and full diagnostics remain private; a sanitized report may
publish source hashes, rejection states and dimensionless numerical comparisons.
One genuine pair is not a volatility surface or a broad market validation set.

Recorded result: 123 focused tests passed, including 29 new diagnostic tests and
the unchanged Phase 7/options-service regressions. On the genuine archived pair,
the 800-by-800 PDE and 1600-step tree layer gamma differ by about 0.0635%; the
original validator still rejects it. The additional 16-case synthetic study
retains one low-gamma out-of-the-money tail case with a difference above the
investigative 1% relative/1e-6 absolute review condition. Further space/time refinement leaves a tail-method disagreement that is not
cleared or relabeled as certification. See the sanitized source-bound
``docs/audits/american-gamma-diagnostic-validation.json``. The new opt-in module's
focused checks do not constitute a new full repository or live options certificate.

Remaining work before a model replacement can be reviewed:

* Broader prespecified moneyness/expiry/volatility/rate cases, particularly near
  early-exercise boundaries, short maturities and non-grid-aligned strikes.
* Joint space/time/domain accuracy and independent reference comparisons over
  that set, including IV repricing consistency and all required Greeks.
* Genuine synchronized options/underlying quote samples with unchanged freshness,
  spread, identity, rate and convention checks. An old capture is historical.
* An explicit reviewed model-admission change with regression evidence; never
  remove a failed test merely because an alternative method looks plausible.
* Published point-in-time OI and declared chain coverage for any unsigned
  OI-weighted exposure. OI alone does not reveal dealer positioning. Signed
  dealer GEX, authoritative flips/walls and GIL certification remain unavailable.

Native futures analysis does not depend on this numerical study. Gamma research
does not fit or inspect the market-data calibration holdouts.

Primary numerical references
------------------------------

K. J. in 't Hout, A note on the numerical approximation of Greeks for
American-style options, https://arxiv.org/abs/2401.13361. In particular,
Crank-Nicolson damping by itself is not a general gamma convergence guarantee.
The present prototype uses first-order implicit Euler; it does not claim to
implement the paper's higher-order DIRK method or reproduce all its results.

P. A. Forsyth and K. R. Vetzal, computational discussion of American-option
constraints and Greeks, https://cs.uwaterloo.ca/~paforsyt/con7.pdf.
