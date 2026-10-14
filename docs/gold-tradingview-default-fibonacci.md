# Gold Fibonacci ratio policy

The user selected TradingView's restored built-in **Auto Fib Retracement** default ratios as the internal Gold analysis/target profile on 2026-10-14. Policy ID: `gold-tradingview-default-ratios-v1`.

| Use | Ratios |
| --- | --- |
| Retracement candidates | 0.236, 0.382, 0.5, 0.618, 0.786 |
| Continuation/extension candidates | 1.0, 1.618, 2.618, 3.618, 4.236 |
| Chart reference endpoints | 0 and 1 |

Safari verification after Reset settings showed deviation3, depth10, Reverse off. Enabled chart levels were 0/.236/.382/.5/.618/.786/1/1.618/2.618/3.618/4.236. Levels .65/1.272/1.414/1.65/2.65/3.65/4.618 and negative levels were disabled. TradingView remains unchanged. [TradingView's official Auto Fib documentation](https://www.tradingview.com/support/solutions/43000585089-auto-fib-retracement/) explains deviation/depth/reverse; the enabled level set was verified directly in this user's restored settings.

## Internal interpretation

This adopts the **ratios**, with Monatise's existing structural anchor selection and directional price conventions. It does not reproduce TradingView's ZigZag pivots, developing anchors, chart reverse semantics or every displayed price. Chart deviation3/depth10 are provenance, not replacement parameters for the confirmed H1 pivot detector.

For a confirmed bullish A low → B high, retracement is B−r×(B−A), continuation is A+r×(B−A). Bearish A high → B low is symmetric. The internal extension1.0 is B; chart endpoint labels must not be mistaken for an identical orientation. Raw ratios/levels and anchor provenance remain distinct from qualified profit targets.

`GoldLayerEvaluator` dispatches Fibonacci assessment/target evidence to `application/gold_fibonacci.py`. Gold advisory assessments use the selected ratio profile. Only the H1 structural layer generates Fib profit candidates; lower frames retain independent liquidity/swing/zone objectives but cannot supply replacement Fib target anchors. Existing H1 anchor confidence/range/age validation remains unchanged. OTE is .618–.786; the Gold deep region begins at .786 without adding an unselected .886 line.

Both retracement and extension levels can be forward objectives depending on the actual entry. Admission still requires an existing engine-reported liquidity, supply/demand or structure confluence. New distant ratios receive no automatic structural-confluence bonus. Existing nearer technical obstacles are retained. The TP builder applies direction, freshness, confidence, mapping-distance, merging, minimum RR, allocation and maximum-target rules. No fixed TP1/TP2/TP3 assignment, automatic profit order or RR improvement is claimed. The saved Run Gold workflow retains its stricter2:1 TP2/all-permitted-fill requirement and3% combined ceiling.

Non-Gold routes retain the old shared Fibonacci defaults and their target behavior. The change adds narrow overridable dispatch methods; generic defaults are unchanged. Phase8 sealed evidence, historical reports, native-options research and the frozen H1 F0 checkout are unchanged. The frozen F0 profile (1.272/1.414/1.618) remains a historical comparison arm; it must not be relabelled as this new profile.

Implementation is on an isolated branch descended from Phase8 `d6be0b1ff69bd88ee88fcd76c9020602dc686171`. No main merge, deployment, trading, approval, paid acquisition or chart-setting change is part of this update. Saved Gold workflow instructions are updated separately so subsequent analyses identify this user-selected override while preserving original source pins.
