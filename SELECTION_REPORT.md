# Selection experiment report

Regenerated 2026-10-20T01:31:48.185Z from `local_data/experiments/selection-c3534f0569677014`. 18,000 attempted synthetic tasks.

All outcomes below are controlled offline simulation, not measurements of real models. CREDIT is non-monetary. Intervals use 30 seed replicates.

| Scenario | Policy | Verified / attempted | Completion % (95% interval) | Credits | Credits / verified | Mean simulated ms | Deadline misses | Switches | Simulated regret |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| expensive-better | random | 553/720 | 76.8 (73.9, 79.7) | 2628 | 4.752 | 33.9 | 138 | 444 | 107.78 |
| expensive-better | cheapest | 390/720 | 54.2 (50.4, 58.0) | 0 | 0.000 | 17.8 | 23 | 0 | 236.02 |
| expensive-better | fixed | 390/720 | 54.2 (50.4, 58.0) | 0 | 0.000 | 17.8 | 23 | 0 | 236.02 |
| expensive-better | reliability | 513/720 | 71.2 (67.8, 74.7) | 1693 | 3.300 | 28.1 | 62 | 33 | 142.27 |
| expensive-better | ucb | 592/720 | 82.2 (80.9, 83.5) | 3105 | 5.245 | 37.4 | 170 | 584 | 86.49 |
| cheap-sufficient | random | 702/720 | 97.5 (96.5, 98.5) | 2652 | 3.778 | 33.2 | 142 | 444 | 37.10 |
| cheap-sufficient | cheapest | 703/720 | 97.6 (96.5, 98.8) | 0 | 0.000 | 15.8 | 5 | 0 | 0.00 |
| cheap-sufficient | fixed | 703/720 | 97.6 (96.5, 98.8) | 0 | 0.000 | 15.8 | 5 | 0 | 0.00 |
| cheap-sufficient | reliability | 705/720 | 97.9 (97.0, 98.9) | 69 | 0.098 | 16.3 | 5 | 1 | 1.02 |
| cheap-sufficient | ucb | 698/720 | 96.9 (95.8, 98.1) | 2335 | 3.345 | 30.8 | 118 | 670 | 32.93 |
| all-equivalent | random | 625/720 | 86.8 (83.7, 89.9) | 0 | 0.000 | 32.1 | 17 | 444 | 0.00 |
| all-equivalent | cheapest | 628/720 | 87.2 (84.9, 89.6) | 0 | 0.000 | 31.5 | 14 | 0 | 0.00 |
| all-equivalent | fixed | 628/720 | 87.2 (84.9, 89.6) | 0 | 0.000 | 31.5 | 14 | 0 | 0.00 |
| all-equivalent | reliability | 628/720 | 87.2 (84.9, 89.6) | 0 | 0.000 | 31.4 | 13 | 3 | 0.00 |
| all-equivalent | ucb | 629/720 | 87.4 (84.7, 90.0) | 0 | 0.000 | 31.9 | 16 | 636 | 0.00 |
| unreliable-cheap | random | 508/720 | 70.6 (66.8, 74.3) | 2603 | 5.124 | 46.6 | 264 | 444 | 154.47 |
| unreliable-cheap | cheapest | 202/720 | 28.1 (24.7, 31.4) | 0 | 0.000 | 46.7 | 226 | 0 | 444.31 |
| unreliable-cheap | fixed | 202/720 | 28.1 (24.7, 31.4) | 0 | 0.000 | 46.7 | 226 | 0 | 444.31 |
| unreliable-cheap | reliability | 605/720 | 84.0 (80.2, 87.8) | 2143 | 3.542 | 42.3 | 227 | 36 | 54.65 |
| unreliable-cheap | ucb | 596/720 | 82.8 (81.1, 84.4) | 3124 | 5.242 | 46.3 | 289 | 610 | 81.56 |
| nonstationary | random | 515/720 | 71.5 (67.8, 75.3) | 2601 | 5.050 | 36.1 | 113 | 444 | 200.35 |
| nonstationary | cheapest | 391/720 | 54.3 (52.7, 55.9) | 0 | 0.000 | 31.0 | 11 | 0 | 294.59 |
| nonstationary | fixed | 391/720 | 54.3 (52.7, 55.9) | 0 | 0.000 | 31.0 | 11 | 0 | 294.59 |
| nonstationary | reliability | 395/720 | 54.9 (52.7, 57.0) | 147 | 0.372 | 31.4 | 19 | 2 | 291.11 |
| nonstationary | ucb | 575/720 | 79.9 (77.4, 82.3) | 2568 | 4.466 | 36.7 | 111 | 574 | 131.96 |

## Paired differences against random

| Scenario | Policy | Verified-rate difference, percentage points (95% interval) |
|---|---|---:|
| expensive-better | cheapest | -22.6 (-27.1, -18.2) |
| expensive-better | fixed | -22.6 (-27.1, -18.2) |
| expensive-better | reliability | -5.6 (-9.7, -1.4) |
| expensive-better | ucb | +5.4 (+2.3, +8.6) |
| cheap-sufficient | cheapest | +0.1 (-1.0, +1.3) |
| cheap-sufficient | fixed | +0.1 (-1.0, +1.3) |
| cheap-sufficient | reliability | +0.4 (-0.6, +1.4) |
| cheap-sufficient | ucb | -0.6 (-1.8, +0.7) |
| all-equivalent | cheapest | +0.4 (-2.6, +3.5) |
| all-equivalent | fixed | +0.4 (-2.6, +3.5) |
| all-equivalent | reliability | +0.4 (-2.6, +3.5) |
| all-equivalent | ucb | +0.6 (-2.6, +3.7) |
| unreliable-cheap | cheapest | -42.5 (-46.1, -38.9) |
| unreliable-cheap | fixed | -42.5 (-46.1, -38.9) |
| unreliable-cheap | reliability | +13.5 (+8.4, +18.5) |
| unreliable-cheap | ucb | +12.2 (+8.3, +16.2) |
| nonstationary | cheapest | -17.2 (-21.1, -13.4) |
| nonstationary | fixed | -17.2 (-21.1, -13.4) |
| nonstationary | reliability | -16.7 (-20.7, -12.6) |
| nonstationary | ucb | +8.3 (+3.7, +12.9) |

Invalid artifacts accepted: 0. Budget violations: 0. Repeat charges: 0 in this single-charge simulation; independent payment fault tests are the evidence for actual retry behavior.

No single policy is presumed best. Cheap-sufficient and all-equivalent are explicit controls; a free provider can be the useful choice. Infrastructure failures remain in the attempted denominator. Conditional completion metrics, all counts and policy decisions are preserved in analysis.json and raw trials.

Regret uses the declared synthetic expected-utility oracle at each learner budget. Price and quality distributions are invented. Confidence intervals are normal approximations without multiplicity correction. See EXPERIMENT_PROTOCOL.md.
