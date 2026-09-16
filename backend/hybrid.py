import copy

import numpy as np
import torch
from torch import nn


class SelectiveStateBlock(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.delta = nn.Linear(width, width)
        self.input_gate = nn.Linear(width, width)
        self.output_gate = nn.Linear(width, width)
        self.decay = nn.Parameter(torch.zeros(width))
        self.normalization = nn.LayerNorm(width)

    def forward(self, sequence):
        state = torch.zeros_like(sequence[:, 0])
        updates = torch.tanh(self.input_gate(sequence))
        gates = torch.sigmoid(self.output_gate(sequence))
        decay = torch.exp(-torch.nn.functional.softplus(self.delta(sequence)) *
                          torch.nn.functional.softplus(self.decay))
        states = []
        for position in range(sequence.shape[1]):
            state = decay[:, position] * state + (1 - decay[:, position]) * updates[:, position]
            states.append(state * gates[:, position])
        return self.normalization(sequence + torch.stack(states, dim=1))


class HybridForecaster(nn.Module):
    def __init__(self, channels, horizon, width=32):
        super().__init__()
        self.embedding = nn.Linear(channels, width)
        self.state = SelectiveStateBlock(width)
        self.attention = nn.MultiheadAttention(width, 4, batch_first=True)
        self.gate = nn.Linear(width * 2, width)
        self.head = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width),
                                  nn.GELU(), nn.Dropout(.15), nn.Linear(width, horizon))

    def forward(self, sequence):
        states = self.state(self.embedding(sequence))
        query = states[:, -1:, :]
        sparse_context = torch.cat([states[:, ::4, :], query], dim=1)
        attended, _ = self.attention(query, sparse_context, sparse_context, need_weights=False)
        local = query[:, 0]
        global_context = attended[:, 0]
        gate = torch.sigmoid(self.gate(torch.cat([local, global_context], dim=-1)))
        return self.head(gate * local + (1 - gate) * global_context)


def fit(train_input, train_target, validation_input, validation_target, epochs, callback):
    torch.set_num_threads(2)
    torch.manual_seed(42)
    network = HybridForecaster(train_input.shape[-1], train_target.shape[-1])
    optimizer = torch.optim.AdamW(network.parameters(), lr=.002, weight_decay=.001)
    loss_function = nn.MSELoss()
    train_tensor = torch.from_numpy(train_input.astype(np.float32))
    target_tensor = torch.from_numpy(train_target.astype(np.float32))
    validation_tensor = torch.from_numpy(validation_input.astype(np.float32))
    validation_targets = torch.from_numpy(validation_target.astype(np.float32))
    best_loss = float('inf')
    best_state = None
    history = []
    for epoch in range(epochs):
        network.train()
        order = torch.randperm(len(train_tensor))
        running = []
        for indices in order.split(64):
            optimizer.zero_grad(set_to_none=True)
            predicted = network(train_tensor[indices])
            loss = loss_function(predicted, target_tensor[indices])
            loss.backward()
            nn.utils.clip_grad_norm_(network.parameters(), 1.0)
            optimizer.step()
            running.append(float(loss.detach()))
        network.eval()
        with torch.no_grad():
            validation_loss = float(loss_function(network(validation_tensor), validation_targets))
        history.append({'step': epoch + 1, 'train_loss': float(np.mean(running)), 'val_loss': validation_loss})
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_state = copy.deepcopy(network.state_dict())
        callback(epoch + 1, history[-1])
    network.load_state_dict(best_state)
    network.eval()
    return network, history


def predict(network, inputs, samples=24):
    torch.set_num_threads(2)
    torch.manual_seed(1729)
    tensor = torch.from_numpy(inputs.astype(np.float32))
    network.eval()
    with torch.no_grad():
        point = network(tensor).numpy()
        for layer in network.modules():
            if isinstance(layer, nn.Dropout):
                layer.train()
        draws = np.stack([network(tensor).numpy() for _ in range(samples)])
    network.eval()
    return point, draws.std(axis=0)
