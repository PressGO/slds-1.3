# IRLS + coordinate descent vs scikit-learn (300,000 real fit rows, 112 inputs)

Objective = mean log-loss + lambda x L1 norm (lower is better). Our solver must reach at least scikit-learn's objective (asserted).

| penalty | objective (ours) | objective (scikit-learn) | difference | largest coefficient gap | inputs kept (ours / sklearn) | ours | scikit-learn |
|---|---|---|---|---|---|---|---|
| lambda_max x 0.01 | 0.02321897 | 0.02330214 | -8.3e-05 | 3.0e-02 | 45 / 45 | 6 IRLS, 2 s | 5000 epochs, 2787 s |
| lambda_max x 0.001 | 0.02232266 | 0.02244734 | -1.2e-04 | 8.9e-02 | 90 / 97 | 7 IRLS, 7 s | 5000 epochs, 3479 s |
| no penalty (vs lbfgs) | 0.02216729 | 0.02216735 | -5.8e-08 | predictions 4.2e-03 | all / all | 10 IRLS | 64 iterations |
| lambda_max x 0.003, weights 0-2 | 0.02225374 | 0.02236583 | -1.1e-04 | 8.7e-02 | 81 / 85 | 6 IRLS | 5000 epochs |
