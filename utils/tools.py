from dataclasses import dataclass
from typing import List, Union
import pickle
from functools import cached_property, partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from numpy.polynomial.polynomial import Polynomial
from scipy.ndimage import gaussian_filter
from tqdm import tqdm


def celsius2kelvin(celsius: np.ndarray) -> np.ndarray:
    return celsius + 273.15


def kelvin2celsius(kelvin: np.ndarray) -> np.ndarray:
    return kelvin - 273.15


@dataclass
class Data:
    frames: np.ndarray
    fpa: np.ndarray
    housing: np.ndarray
    blackbody: np.ndarray

    def __post_init__(self):
        self.frames = np.stack(self.frames).astype('float32')
        self.fpa = np.array(self.fpa).astype('float32') 
        self.housing = np.array(self.housing).astype('float32')
        self.blackbody = np.array(self.blackbody).astype('float32')

    def U100C2C(self):
        self.fpa /= 100
        self.housing /= 100
        self.blackbody /= 100

    def C2K(self, verbose: bool = True):
        if verbose:
            print(f'FPA temperatures limits: {min(self.fpa):.1f}C - {max(self.fpa):.1f}C')
            print(f'BlackBody temperatures limits: {min(self.blackbody):.1f}C - {max(self.blackbody):.1f}C')
        self.fpa = celsius2kelvin(self.fpa)
        self.housing = celsius2kelvin(self.housing)
        self.blackbody = celsius2kelvin(self.blackbody)
        if verbose:
            print(f'FPA temperatures limits: {min(self.fpa):.1f}K - {max(self.fpa):.1f}K')
            print(f'BlackBody temperatures limits: {min(self.blackbody):.1f}K - {max(self.blackbody):.1f}K')

    def K2C(self):
        if verbose:
            print(f'FPA temperatures limits: {min(self.fpa):.1f}K - {max(self.fpa):.1f}K')
            print(f'BlackBody temperatures limits: {min(self.blackbody):.1f}K - {max(self.blackbody):.1f}K')
        self.fpa = kelvin2celsius(self.fpa)
        self.housing = kelvin2celsius(self.housing)
        self.blackbody = kelvin2celsius(self.blackbody)
        if verbose:
            print(f'FPA temperatures limits: {min(self.fpa):.1f}C - {max(self.fpa):.1f}C')
            print(f'BlackBody temperatures limits: {min(self.blackbody):.1f}C - {max(self.blackbody):.1f}C')

    def __len__(self):
        return len(self.fpa)

    @cached_property
    def h(self):
        return self.frames[0].shape[-2]
    
    @cached_property
    def w(self):
        return self.frames[0].shape[-1]

    def sort(self, key: str):
        if key == 'fpa':
            indices = np.lexsort([self.blackbody, self.fpa])
        elif key == 'blackbody':
            indices = np.lexsort([self.fpa, self.blackbody])
        self.frames = self.frames[indices]
        self.fpa = self.fpa[indices]
        self.blackbody = self.blackbody[indices]
        self.housing = self.housing[indices] if self.housing is not None and len(self.housing) == len(indices) else self.housing

    @property
    def max_gl(self):
        return np.max(self.frames)

    @property
    def min_gl(self):
        return np.min(self.frames)



def _loader(p) -> dict:
    fp = np.load(p)
    return {k:fp[k] for k in fp.keys()}


def load_measurements(path_to_files: Union[str, Path] = None) -> Data:
    if path_to_files:
        path_to_files = Path(path_to_files)
    else:
        print('No path given. Assumes /rawData')
        path_to_files = Path.cwd()
        while not (path_to_files / "rawData").is_dir():
            path_to_files = path_to_files.parent
        path_to_files = path_to_files / "rawData"

    data = {}
    list_path = list(sorted(list(path_to_files.glob('*.npz'))))
    with Pool(min(len(list_path), cpu_count())) as pool:
        results = list(tqdm(pool.imap(_loader, list_path), desc='Loading', total=len(list_path)))
    for res in filter(lambda x: 'frames' in x.keys(), results):
        for k, v in res.items():
            data.setdefault(k, []).extend(v)

    # constraint all frames to a rectangular shape
    data['frames'] = [same_dim(p) for p in data['frames']]

    return Data(frames=data['frames'], fpa=data['fpa'], housing=data['housing'], blackbody=data['blackbody'])


def same_dim(image: np.ndarray, crop_size: int = 0):
    try:
        h, w = image.shape
        diff = abs(h - w) // 2
        if h > w:
            image = image[diff:-diff, ...]
        elif h < w:
            image = image[..., diff:-diff]
        if crop_size > 0:
            image = image[crop_size:-crop_size, crop_size:-crop_size]
    except ValueError:
        pass
    return image


def clean_noise(data: dict, sigma: int = 2, plot_before_after: bool = False):
    ex_fpa = np.random.choice(list(data.keys()))
    ex_bb = np.random.choice(list(data[ex_fpa]['measurements'].keys()))
    ex_idx = np.random.choice(data[ex_fpa]['measurements'][ex_bb].shape[0])
    before = data[ex_fpa]['measurements'][ex_bb][ex_idx].copy()

    n_samples = len(data) * len(data[list(data.keys())[0]]['measurements'])
    # data_list = []
    # for t_fpa, d in data.items():
    #     for t_bb, v in d.items():
    #         data_list.append((t_fpa, t_bb, v))
    #
    # with Pool(cpu_count()) as pool:
    #     data_list = list(tqdm(pool.imap(_cleaner, data_list, chunksize=2**2),
    #                           desc='Gaussian Filter', total=n_samples))
    #
    # for (t_fpa, t_bb, images) in data_list:
    #     data[t_fpa][t_bb] = images
    # del data_list

    with tqdm(total=n_samples, desc='Gaussian Filter') as pbar:
        for fpa, d in data.items():
            for t_bb, dt in d['measurements'].items():
                data[fpa]['measurements'][t_bb] = np.stack([gaussian_filter(p, sigma=sigma) for p in dt])
                pbar.update()
    if plot_before_after:
        after = data[ex_fpa]['measurements'][ex_bb][ex_idx, ...]
        vmin, vmax = min(after.min(), before.min()), max(after.max(), before.max())
        fig, axs = plt.subplots(1, 2, figsize=(16, 9), sharey='all', sharex='all', facecolor='white')
        im = axs[0].imshow(before, cmap='coolwarm')
        im.set_clim(vmin, vmax)
        plt.colorbar(im, ax=axs[0])
        axs[0].set_title('Before')
        im = axs[1].imshow(after, cmap='coolwarm')
        im.set_clim(vmin, vmax)
        plt.colorbar(im, ax=axs[1])
        axs[1].set_title('After')
        plt.tight_layout()
        plt.show()
    return data


def fit_housing_to_fpa(data: dict, *, order: int = 2, plot: bool = False) -> Polynomial:
    df = pd.DataFrame({t_fpa: pd.DataFrame(data[t_fpa]['housing']).mean() for t_fpa in data.keys()})
    df = df.reindex(sorted(df.columns), axis=1)
    df = df.reindex(sorted(df.index), axis=0)
    df = df.mean()

    if plot:
        plt.figure()
        sns.regplot(x=df.index / 100, y=(df - df.index) / 100, order=order)
        plt.grid()
        plt.title('Difference between FPA to Housing temperatures')
        plt.xlabel('FPA [C]')
        plt.ylabel('Difference [C]')
        plt.tight_layout()
        plt.show()
        plt.close()

    p = Polynomial.fit(df.index, df, deg=order)
    # noinspection PyUnresolvedReferences
    return p.convert(window=p.domain, domain=p.domain)


def make_uniqe_dict(data) -> dict:
    uniqus = {}
    for fpa, bb, frame in zip(data.fpa, data.blackbody, data.frames):
        uniqus.setdefault(fpa, {}).setdefault(bb, []).append(frame)
    return uniqus


def make_std_dict(data):
    stds = {}
    uniqus = make_uniqe_dict(data)

    for fpa, v in uniqus.items():
        for bb, vv in v.items():
            uniqus[fpa][bb] = np.stack(vv)
            stds.setdefault(fpa, {}).setdefault(bb, uniqus[fpa][bb].std(0).mean())

    return stds


def constrain_measurements_by_std(data: Data, threshold: int = 5, plot_top_three: bool = False, verbose: bool = False):
    stds = make_std_dict(data)

    list_above_threshold = []
    for fpa, v in stds.items():
        for bb, vv in v.items():
            list_above_threshold.append((fpa, bb, vv)) if vv > threshold else None
    list_above_threshold.sort(key=lambda x: x[-1], reverse=True)
    if verbose:
        [print(p) for p in list_above_threshold]
    list_above_threshold = [(fpa, bb) for fpa, bb, _ in list_above_threshold]

    list_indices_in_data = []
    for idx, (fpa, bb) in enumerate(zip(data.fpa, data.blackbody)):
        if (fpa, bb) in list_above_threshold:
            list_indices_in_data.append(idx)

    if plot_top_three:
        df = pd.DataFrame.from_dict(make_uniqe_dict(data))
        for idx in range(min(3, len(list_above_threshold))):
            fpa, bb = list_above_threshold[idx]
            plt.figure()
            plt.plot(np.stack(df.loc[bb][fpa])[:, 128, 128])
            plt.title(f"{fpa} {bb} {np.stack(df.loc[bb][fpa])[:, 128, 128].std():.2g}")
            plt.show()
            plt.close()

    indices = list(set(range(len(data.fpa))) - set(list_indices_in_data))
    data.fpa = data.fpa[indices]
    data.housing = data.housing[indices]
    data.blackbody = data.blackbody[indices]
    data.frames = data.frames[indices]
    return data