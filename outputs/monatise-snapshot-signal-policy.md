# Monatise Snapshot Signal Policy

## Purpose

Monatise should not flip BUY, SELL, BUY, SELL every few seconds. A professional signal desk should take a decision snapshot, issue fixed execution levels, and reassess on a clear window.

## Layers

### Market Data Layer

These inputs can update continuously:

- Liquidations
- Long/short ratios
- Volume
- CVD
- Liquidity sweeps
- CHoCH/BOS
- FVGs
- Grid execution context
- Structural invalidation

Live inputs are market observation. They should not directly rewrite an active setup on every refresh.

### Decision Layer

At a specific time, Monatise takes a snapshot:

- Analyze the market context
- Lock the metrics used for the decision
- Generate bias
- Keep the bias fixed for 15-30 minutes

This prevents constant signal flipping.

### Execution Layer

Once the trade setup is active:

- Stop loss stays fixed
- Invalidation stays fixed
- Targets stay fixed
- Entry logic stays tied to the original snapshot

Only a major structural invalidation event should cancel the setup.

## User Experience

A high-value trader does not want:

> Buy -> Sell -> Buy -> Sell every 30 seconds

They want:

> At 9:00 AM, probability favored buyers. Here is the entry, invalidation, and target. Reassess in 30 minutes.

That feels professional and actionable.

## Implementation Rules

1. A generated BUY or SELL becomes a locked active snapshot.
2. The snapshot keeps its entry, invalidation, target, grids, and hedge fixed for 30 minutes.
3. Conflicting live data inside the lock window becomes a watch state, not an immediate bias flip.
4. The setup cancels only when price crosses invalidation and the framework confirms strong opposite structure.
5. After cancellation, Monatise waits for a fresh snapshot before issuing another active setup.

