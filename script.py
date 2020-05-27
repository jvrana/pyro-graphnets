from os.path import abspath
from os.path import dirname
from os.path import join
from pyro_graph_nets.utils.tensorboard import new_writer as new_summary_writer

runs = join(abspath(dirname(__file__)), ".runs")

def new_writer():
    """Return a function that creates a new writer.

    .. code-block:: python

        def test_writer(new_writer):
            writer = new_writer('my_directory', suffix='_test')
    :return:
    """

    def make_new_writer(directory, *args, **kwargs):
        return new_summary_writer(join(runs, directory), *args, **kwargs)

    return make_new_writer


from pyro_graph_nets.examples.shortest_path import generate_networkx_graphs
import numpy as np

import torch
from pyro_graph_nets.flex import Flex
from pyro_graph_nets.models import GraphEncoder, GraphNetwork
from pyro_graph_nets.blocks import EdgeBlock, NodeBlock, GlobalBlock, MLP, Aggregator
from pyro_graph_nets.utils.graph_tuple import cat_gt, to_graph_tuple
from pyro_graph_nets.utils.data import GraphDataLoader, GraphDataset


class EncodeProcessDecode(torch.nn.Module):
    def __init__(self):
        super().__init__()
        FlexMLP = Flex(MLP)
        self.encoder = GraphEncoder(
            EdgeBlock(FlexMLP(Flex.d(), 16, 5), independent=True),
            NodeBlock(FlexMLP(Flex.d(), 16, 5), independent=True),
            None,
        )

        # note that core should have the same output dimensions as the encoder
        self.core = GraphNetwork(
            EdgeBlock(FlexMLP(Flex.d(), 16, 5), independent=False),
            NodeBlock(
                FlexMLP(Flex.d(), 16, 5),
                independent=False,
                edge_aggregator=Aggregator("mean"),
            ),
            GlobalBlock(FlexMLP(Flex.d(), 1), independent=True),
        )

        self.decoder = GraphEncoder(
            EdgeBlock(FlexMLP(Flex.d(), 16, 1), independent=True),
            NodeBlock(FlexMLP(Flex.d(), 16, 1), independent=True),
            GlobalBlock(MLP(1, 1), independent=True),
        )

        # self.output_transform = GraphEncoder(
        #     EdgeBlock(Flex(torch.nn.Linear)(Flex.d(), 1), independent=True),
        #     NodeBlock(Flex(torch.nn.Linear)(Flex.d(), 1), independent=True),
        #     GlobalBlock(
        #         MLP(1, 1),
        #         independent=True
        #     )
        # )

    def forward(self, input_gt, num_steps: int):
        latent = self.encoder(input_gt)
        latent0 = latent

        output = []
        for step in range(num_steps):
            core_input = cat_gt(latent0, latent)
            latent = self.core(core_input)
            decoded = self.decoder(latent)
            # out = self.output_transform(decoded)
            output.append(decoded)
        return output


def test_shortest_path_examples():

    writer = new_writer()("shortest_path")

    rand = np.random.RandomState(2)
    input_graphs, target_graphs, _ = generate_networkx_graphs(rand, 10, (2, 20), 20)

    nodes = list(input_graphs[0].nodes(data=True))
    print(nodes[0])

    edges = list(input_graphs[0].edges(data=True))
    print(edges[0])

    # preprocessed graphs
    def preprocess(graphs):
        for graph in graphs:
            for _, ndata in graph.nodes(data=True):
                ndata["x"] = torch.tensor(ndata["features"][:3])
                ndata["y"] = torch.tensor([ndata["solution"]])

            for _, _, edata in graph.edges(data=True):
                edata["x"] = torch.tensor(edata["features"])
                edata["y"] = torch.tensor([edata["solution"]])

    # training loader
    input_graphs, _, _ = generate_networkx_graphs(rand, 100, (2, 50), 20)
    preprocess(input_graphs)
    dataset = GraphDataset(input_graphs)
    n_train = int((len(dataset) * 0.9))
    n_test = len(dataset) - n_train
    train_set, test_set = torch.utils.data.random_split(dataset, [n_train, n_test])
    loader = GraphDataLoader(train_set, batch_size=50, shuffle=True)
    test_loader = GraphDataLoader(test_set, batch_size=50, shuffle=False)

    model = EncodeProcessDecode()

    # prime the model
    input_gt = to_graph_tuple([dataset[0]], feature_key="x")
    with torch.no_grad():
        model(input_gt, 10)

    # writer.add_graph(model, (input_gt, 10))

    optimizer = torch.optim.Adam(lr=0.001, params=model.parameters())
    criterion = torch.nn.BCEWithLogitsLoss()

    def loss_fn(outputs, target_gt):
        return criterion(outputs[-1].node_attr, target_gt.node_attr) + criterion(
            outputs[-1].edge_attr, target_gt.edge_attr
        )

    running_loss = 0.0
    num_epochs = 30
    num_steps = 10

    device = "cuda:0"
    model.to(device)
    x = next(model.parameters()).is_cuda
    for epoch in range(num_epochs):

        # min batch
        for batch_ndx, bg in enumerate(loader):
            input_gt = to_graph_tuple(bg, feature_key="x", device=device)
            target_gt = to_graph_tuple(bg, feature_key="y", device=device)

            # zero the parameter gradients
            optimizer.zero_grad()

            # forward + backward + optimize
            outputs = model(input_gt, num_steps)
            loss = torch.sum(loss_fn(outputs, target_gt)) / num_steps
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

        with torch.no_grad():
            running_test_loss = 0.0
            for test_batch in test_loader:
                test_input_gt = to_graph_tuple(
                    test_batch, feature_key="x", device=device
                )
                test_target_gt = to_graph_tuple(
                    test_batch, feature_key="y", device=device
                )

                test_outputs = model(test_input_gt, num_steps)
                test_loss = loss_fn(test_outputs, test_target_gt)
                running_test_loss += test_loss.item()
        writer.add_scalar("test_loss", running_test_loss, epoch)

        writer.add_scalar("training loss", running_loss, epoch)
        running_loss = 0.0


test_shortest_path_examples()
