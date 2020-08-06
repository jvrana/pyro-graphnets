from pyrographnets.blocks import MLP, EdgeBlock, AggregatingEdgeBlock
import torch

def test_init_edge_block():
    edge_encoder = EdgeBlock(MLP(3, 10, 16))

    x = torch.randn(20, 3)
    out = edge_encoder(x)
    assert out.shape == torch.Size([20, 16])

    for p in edge_encoder.parameters():
        assert p.requires_grad


def test_init_agg_edge_block():
    edge_model = AggregatingEdgeBlock(MLP(7, 10, 16))

    x = torch.randn(20, 3)
    edges = torch.randint(0, 40, torch.Size([2, 20]))
    n = torch.randn(40, 2)

    assert edge_model(x, n, edges).shape == torch.Size([20, 16])

    for p in edge_model.parameters():
        assert p.requires_grad