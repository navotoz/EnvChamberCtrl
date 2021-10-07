import csv
import struct
from itertools import product

import matplotlib.pyplot as plt

path = '/home/lab/EnvChamber/src/thermapp_header_dump.csv'
row_14 = []
row_15 = []
with open(path, 'r') as fp:
    for row in csv.reader(fp):
        row_14.append(int(row[0]))
        row_15.append(int(row[1]))


def byte_me(to_bytes_reg, to_num_reg, denominator=1.):
    return list(map(lambda x: struct.unpack(to_num_reg, x)[0] * denominator,
                    list(map(lambda x, y: struct.pack(to_bytes_reg, x, y), row_14, row_15))))


def plot_combined(a1, a2, b1, b2, denominator=1.):
    x = range(0, len(row_14))
    for a, b in product((a1, a2), (b1, b2)):
        if not a or not b:
            continue
        fig, ax = plt.subplots()
        ax.plot(x, byte_me(a, b, denominator), label=f'{a} {b}')
        ax.xaxis.set_major_locator(plt.MaxNLocator(10))
        ax.yaxis.set_major_locator(plt.MaxNLocator(10))
        ax.grid()
        plt.legend()
        plt.show()
        plt.close()


def plot_rows():
    x = range(0, len(row_14))
    fig, ax = plt.subplots()
    ax.plot(x, row_14, label='14')
    ax.plot(x, row_15, label='15')
    ax.xaxis.set_major_locator(plt.MaxNLocator(10))
    ax.yaxis.set_major_locator(plt.MaxNLocator(10))
    ax.grid()
    plt.legend()
    plt.show()
    plt.close()


def plot_double():
    x = range(0, len(row_14))
    fig, ax = plt.subplots()
    color_left = 'red'
    plt.plot(x, row_14, label='14', color=color_left)
    ax.xaxis.set_major_locator(plt.MaxNLocator(10))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(10))
    ax.yaxis.set_major_locator(plt.MaxNLocator(10))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(10))
    ax.set_ylabel('14', color=color_left)
    ax.tick_params(axis='y', labelcolor=color_left)

    ax2 = ax.twinx()  # instantiate a second axes that shares the same x-axis
    color_right = 'blue'
    plt.plot(x, row_15, label='15', color=color_right)
    ax2.xaxis.set_major_locator(plt.MaxNLocator(10))
    ax2.xaxis.set_minor_locator(plt.MaxNLocator(10))
    ax2.yaxis.set_major_locator(plt.MaxNLocator(10))
    ax2.yaxis.set_minor_locator(plt.MaxNLocator(10))
    ax2.set_ylabel('14', color=color_right)
    ax2.tick_params(axis='y', labelcolor=color_right)
    fig.legend()
    plt.tight_layout()
    plt.grid()
    plt.show()
    plt.close()


i = byte_me('<HH', '<I')
f = byte_me('<HH', '<f')

xi = 5 / 63271718
bi = -72.94083957

xf = 0.00071663468
bf = 0.9999999832

# plt.figure()
# plt.plot(list(map(lambda y:y*xf+bf, f)))
# plt.grid()
# plt.show()
# plt.close()
#
# plt.figure()
# plt.plot(list(map(lambda y:y*xi+bi, i)))
# plt.grid()
# plt.show()
# plt.close()

plot_combined(None, '<HH', None, '<I', denominator=1e-6)
plot_combined(None, '<HH', None, '<f', denominator=1e-3)

# plot_rows()
# plot_double()
