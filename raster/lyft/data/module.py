from argparse import ArgumentParser
import typing as th
from raster.utils import boolify
from torch.utils.data import DataLoader, Subset, random_split
from pytorch_lightning import LightningDataModule
import pandas as pd

from l5kit.rasterization import build_rasterizer
from l5kit.data import LocalDataManager, ChunkedDataset
from l5kit.dataset import AgentDataset

DEFAULT_BATCH_SIZE = 32
DEFAULT_CACHE_SIZE = int(1e9)
DEFAULT_NUM_WORKERS = 4


class LyftDataModule(LightningDataModule):
    def __init__(
            self,
            data_root: str,
            config: dict,
            # train
            train_split: str = None,
            train_batch_size: str = None,
            train_shuffle: bool = None,
            train_num_workers: int = None,
            train_idxs: th.Any = None,
            # validation
            val_proportion: float = None,
            val_split: str = None,
            val_batch_size: str = None,
            val_shuffle: bool = None,
            val_num_workers: int = None,
            val_idxs: th.Any = None,
            # overall options
            cache_size: float = 1e9,
    ):
        super().__init__()
        self.data_root = data_root
        self.config = config
        print('initializing up data module\n\t*root:', data_root)

        # train
        self.train_split = train_split or config['train_dataloader']['split']
        self.train_batch_size = train_batch_size or config['train_dataloader']['batch_size']
        self.train_shuffle = train_shuffle or config['train_dataloader'].get('shuffle', True)
        self.train_num_workers = train_num_workers if train_num_workers is not None else config['train_dataloader'].get(
            'num_workers', DEFAULT_NUM_WORKERS)
        self.train_idxs = None if train_idxs is None else pd.read_csv(train_idxs)['idx']
        print('train\n\t*split:', self.train_split, '*batch_size:', self.train_batch_size, '*shuffle:',
              self.train_shuffle, '*num_workers:', self.train_num_workers, '*idxs:', train_idxs)
        # val
        self.val_proportion = val_proportion
        self.val_split = val_split or config.get('val_dataloader', dict()).get('split', None)
        self.val_batch_size = val_batch_size or config.get('val_dataloader', dict()).get(
            'batch_size', self.train_batch_size)
        self.val_shuffle = val_shuffle or config.get('val_dataloader', dict()).get('shuffle', False)
        self.val_num_workers = val_num_workers if val_num_workers is not None else config.get(
            'val_dataloader', dict()).get('num_workers', DEFAULT_NUM_WORKERS)
        self.val_idxs = None if val_idxs is None else pd.read_csv(val_idxs)['idx']
        assert self.val_split is not None or self.val_proportion is not None, \
            'validation proportion should not be None'
        print('val\n\t*split:', self.val_split, '*batch_size:', self.val_batch_size, '*shuffle:', self.val_shuffle,
              '*num_workers:', self.val_num_workers, '*idxs:', val_idxs, '*proportion:', self.val_proportion)

        # attributes
        self.cache_size = int(cache_size)
        self.data_manager = None
        self.rasterizer = None
        self.train_data = None
        self.val_data = None

    def setup(self, stage=None):
        if self.data_manager is None:
            self.data_manager = LocalDataManager(self.data_root)
        if self.rasterizer is None:
            self.rasterizer = build_rasterizer(self.config, self.data_manager)
        if stage == 'fit' or stage is None:
            train_zarr = ChunkedDataset(self.data_manager.require(self.train_split)).open(
                cache_size_bytes=int(self.cache_size))
            train_data = AgentDataset(self.config, train_zarr, self.rasterizer)
            if self.train_idxs is not None:
                train_data = Subset(train_data, self.train_idxs)
            if self.val_split is None or self.val_split == self.train_split:
                tl = len(train_data)
                vl = int(tl * self.val_proportion)
                self.train_data, self.val_data = random_split(train_data, [tl - vl, vl])
            else:
                val_zarr = ChunkedDataset(self.data_manager.require(self.val_split)).open(
                    cache_size_bytes=int(self.cache_size))
                self.val_data = AgentDataset(self.config, val_zarr, self.rasterizer)
                if self.val_idxs is not None:
                    self.val_data = Subset(train_data, self.val_idxs)

    def _get_dataloader(self, name: str, batch_size=None, num_workers=None, shuffle=None):
        batch_size = batch_size or getattr(self, f'{name}_batch_size')
        num_workers = num_workers or getattr(self, f'{name}_num_workers')
        shuffle = shuffle or getattr(self, f'{name}_shuffle')
        return DataLoader(
            getattr(self, f'{name}_data'), batch_size=batch_size, num_workers=num_workers, shuffle=shuffle)

    def train_dataloader(self, batch_size=None, num_workers=None, shuffle=None):
        return self._get_dataloader('train', batch_size=batch_size, num_workers=num_workers, shuffle=shuffle)

    def val_dataloader(self, batch_size=None, num_workers=None, shuffle=None):
        return self._get_dataloader('val', batch_size=batch_size, num_workers=num_workers, shuffle=shuffle)

    @staticmethod
    def add_model_specific_args(parent_parser):
        parser = ArgumentParser(parents=[parent_parser], add_help=False)
        parser.add_argument('--data-root', required=True, type=str, help='lyft dataset root folder path')
        parser.add_argument('--cache-size', type=float, default=1e9, help='cache size for each data split')

        parser.add_argument('--train-split', type=str, default=None, help='train split scenes')
        parser.add_argument('--train-batch-size', type=int, help='train batch size of dataloaders')
        parser.add_argument('--train-shuffle', type=boolify, default=None, help='train dataloader shuffle data')
        parser.add_argument('--train-num-workers', type=int, default=None, help='train dataloader number of workers')
        parser.add_argument('--train-idxs', type=str, default=None, help='train data indexes')

        parser.add_argument('--val-proportion', type=float, default=None, help='validation proportion in data')
        parser.add_argument('--val-split', type=str, default=None, help='validation split scenes')
        parser.add_argument('--val-batch-size', type=int, default=None, help='validation batch size of dataloaders')
        parser.add_argument('--val-shuffle', type=boolify, default=None, help='validation dataloader shuffle data')
        parser.add_argument('--val-num-workers', type=int, default=None, help='validation dataloader number of workers')
        parser.add_argument('--val-idxs', type=str, default=None, help='validation data indexes')
        return parser
