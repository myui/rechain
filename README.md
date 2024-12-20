rtrec: Realtime Recommendation Library in Python
================================================

[![PyPI version](https://img.shields.io/pypi/v/pypistats.svg?logo=pypi&logoColor=FFE873)](https://pypi.org/project/rtrec/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/pypistats.svg?logo=python&logoColor=FFE873)](https://pypi.org/project/rtrec/)
[![CI status](https://github.com/myui/rtrec/workflows/Test/badge.svg)](https://github.com/myui/rtrec/actions)
[![Licence](https://img.shields.io/github/license/myui/rtrec.svg)](LICENSE.txt)

An realtime recommendation system supporting online updates.

## Highlights

- ❇️ Supporting online updates.
- ⚡️ Fast implementation (>=190k samples/sec training on laptop).
- ◍ efficient sparse data support.
- 🕑 decaying weights of user-item interactions based on recency.

## Supported Recommendation Algorithims

- Sparse [SLIM](https://ieeexplore.ieee.org/document/6137254) with [time-weighted](https://dl.acm.org/doi/10.1145/1099554.1099689) interactions.
- [Factorization Machines] using [LightFM](https://github.com/lyst/lightfm) (to appear)

## Installation

```sh
pip install rtrec
```

## Usage

Find usages in [notebooks](https://github.com/myui/rtrec/tree/main/notebooks)/[examples](https://github.com/myui/rtrec/blob/main/examples/streamlit/movielens_dashboard.py).
