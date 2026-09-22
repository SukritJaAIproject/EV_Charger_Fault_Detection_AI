"""Competitor 5 — Reinforcement Learning.

Fault detection framed as optimal stopping: at every step the policy chooses
WAIT or ALERT. First ALERT ends the decision problem for the session.

  state    last 4 feature vectors stacked (4 x 33 = 132) — short-term dynamics
  actions  0 = WAIT, 1 = ALERT
  reward   +1 + earliness bonus for a correct (early) alert,
           -1.5 for a false alarm, -1 for a missed fault,
           +0.3 for staying quiet through a clean session

Trained with Double DQN + replay on the GPU (train/train_rl.py). At
inference the greedy policy runs on every v2g/tcp/slac step.
"""
import os
from collections import deque

import numpy as np
import torch
import torch.nn as nn

from core.detector_base import Detector
from core.feature_tracker import FeatureState

from core.paths import ARTIFACTS as ART  # noqa: E402
STACK = 4
N_STATE = FeatureState.N_FEATURES * STACK


class QNet(nn.Module):
    def __init__(self, n_in=N_STATE, hidden=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, 2),
        )

    def forward(self, x):
        return self.net(x)


class StackedState:
    def __init__(self):
        self.buf = deque(maxlen=STACK)

    def reset(self):
        self.buf.clear()

    def push(self, vec):
        self.buf.append(vec)
        return self.state()

    def state(self):
        if not self.buf:
            return np.zeros(N_STATE, dtype=np.float32)
        pads = [self.buf[0]] * (STACK - len(self.buf)) + list(self.buf)
        return np.concatenate(pads).astype(np.float32)


class RLDetector(Detector):
    name = "RL"

    def __init__(self, margin=0.0):
        # pure-numpy greedy policy (verified equivalent to the torch QNet)
        from models.fast_infer import NumpyMLP
        ckpt = torch.load(os.path.join(ART, "dqn.pt"), map_location="cpu",
                          weights_only=False)
        self.policy = NumpyMLP(ckpt["state"])
        self.margin = ckpt.get("margin", margin)
        self.stack = StackedState()
        self.done = False

    def reset(self, station, connector):
        self.stack.reset()
        self.done = False

    def observe(self, ev, fs):
        if self.done or ev.kind == "hpav" and "LINK_STATUS" in ev.msg:
            # LINK_STATUS polling is not a decision step (matches training)
            return []
        s = self.stack.push(np.asarray(fs.as_vector(), dtype=np.float32))
        qv = self.policy.forward(s)
        adv = float(qv[1] - qv[0])
        if adv > self.margin:
            self.done = True
            return [self.alert(fs.t, 0.9,
                               f"policy: Q(alert)-Q(wait)={adv:.2f}")]
        return []
