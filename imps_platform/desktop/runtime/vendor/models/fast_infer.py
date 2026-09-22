"""Minimal pure-NumPy LSTM/GRU inference copied from the audited AI project."""

from __future__ import annotations

import numpy as np


def _lstm_seq(x, weight_ih, weight_hh, bias, hidden_size):
    """Run an LSTM sequence using PyTorch-compatible gate ordering."""
    steps = x.shape[0]
    states = np.empty((steps, hidden_size), dtype=np.float32)
    hidden = np.zeros(hidden_size, dtype=np.float32)
    cell = np.zeros(hidden_size, dtype=np.float32)
    input_gates = x @ weight_ih.T + bias
    for index in range(steps):
        gates = input_gates[index] + weight_hh @ hidden
        ingate = 1.0 / (1.0 + np.exp(-gates[:hidden_size]))
        forgetgate = 1.0 / (1.0 + np.exp(-gates[hidden_size : 2 * hidden_size]))
        cellgate = np.tanh(gates[2 * hidden_size : 3 * hidden_size])
        outgate = 1.0 / (1.0 + np.exp(-gates[3 * hidden_size :]))
        cell = forgetgate * cell + ingate * cellgate
        hidden = outgate * np.tanh(cell)
        states[index] = hidden
    return hidden, states


class NumpyLSTMAE:
    def __init__(self, state_dict, n_feat, hidden=64, latent=16):
        del n_feat, latent
        state = {key: np.asarray(value, dtype=np.float32) for key, value in state_dict.items()}
        self.hidden_size = hidden
        self.encoder_ih = state["enc.weight_ih_l0"]
        self.encoder_hh = state["enc.weight_hh_l0"]
        self.encoder_bias = state["enc.bias_ih_l0"] + state["enc.bias_hh_l0"]
        self.to_latent_weight = state["to_latent.weight"]
        self.to_latent_bias = state["to_latent.bias"]
        self.from_latent_weight = state["from_latent.weight"]
        self.from_latent_bias = state["from_latent.bias"]
        self.decoder_ih = state["dec.weight_ih_l0"]
        self.decoder_hh = state["dec.weight_hh_l0"]
        self.decoder_bias = state["dec.bias_ih_l0"] + state["dec.bias_hh_l0"]
        self.output_weight = state["out.weight"]
        self.output_bias = state["out.bias"]

    def recon_error(self, values):
        values = np.asarray(values, dtype=np.float32)
        hidden, _ = _lstm_seq(
            values, self.encoder_ih, self.encoder_hh, self.encoder_bias, self.hidden_size
        )
        latent = self.to_latent_weight @ hidden + self.to_latent_bias
        seed = self.from_latent_weight @ latent + self.from_latent_bias
        decoder_input = np.repeat(seed[None, :], values.shape[0], axis=0)
        _, states = _lstm_seq(
            decoder_input,
            self.decoder_ih,
            self.decoder_hh,
            self.decoder_bias,
            self.hidden_size,
        )
        reconstruction = states @ self.output_weight.T + self.output_bias
        return float(((reconstruction - values) ** 2).mean())


class NumpyGRU:
    def __init__(self, state_dict, hidden=48):
        state = {key: np.asarray(value, dtype=np.float32) for key, value in state_dict.items()}
        self.hidden_size = hidden
        self.weight_ih = state["gru.weight_ih_l0"]
        self.weight_hh = state["gru.weight_hh_l0"]
        self.bias_ih = state["gru.bias_ih_l0"]
        self.bias_hh = state["gru.bias_hh_l0"]
        self.head_weight = state["head.weight"]
        self.head_bias = state["head.bias"]

    def predict(self, values):
        values = np.asarray(values, dtype=np.float32)
        size = self.hidden_size
        hidden = np.zeros(size, dtype=np.float32)
        input_gates = values @ self.weight_ih.T + self.bias_ih
        for index in range(values.shape[0]):
            hidden_gates = self.weight_hh @ hidden + self.bias_hh
            reset = 1.0 / (1.0 + np.exp(-(input_gates[index][:size] + hidden_gates[:size])))
            update = 1.0 / (
                1.0
                + np.exp(
                    -(input_gates[index][size : 2 * size] + hidden_gates[size : 2 * size])
                )
            )
            candidate = np.tanh(
                input_gates[index][2 * size :] + reset * hidden_gates[2 * size :]
            )
            hidden = (1.0 - update) * candidate + update * hidden
        return self.head_weight @ hidden + self.head_bias


__all__ = ["NumpyGRU", "NumpyLSTMAE"]
