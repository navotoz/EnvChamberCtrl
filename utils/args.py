import argparse


def _args_base(desc: str):
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument('--filename', help="The name of the measurements file", default='', type=str)
    return parser


def _args_bb_basic(parser):
    parser.add_argument('--blackbody_max', type=int, default=70, help=f"The maximal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_min', type=int, default=10, help=f"The minimal value of the Blackbody in Celsius")
    parser.add_argument('--n_samples', type=int, required=True,
                        help=f"The number of samples to take at each Blackbody stop.")
    return parser


def args_meas_bb_times():
    parser = _args_base('Check the time it takes the Blackbody to climb and to descend.')
    parser = _args_bb_basic(parser)
    parser.add_argument('--blackbody_increments', type=float, required=True,
                        help=f"The increments in the Blackbody temperature. Allowed values [0.1, 10] C")
    return parser.parse_args()


def args_rand_bb():
    parser = _args_base('Set the oven to the highest temperature possible and cycle the Blackbody to different Tbb.'
                        'The images are saved as a dict in a pickle file.')
    # camera
    parser.add_argument('--lens_number', help=f"The lens number for calibration.", type=int, required=True)
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)
    parser.add_argument('--ffc', default=0,
                        help='A temperature at which the camera performs FFC once. If 0 - performs every 30 seconds.')
    # blackbody
    parser = _args_bb_basic(parser)
    parser.add_argument('--bins', type=int, default=6, help="The number of bins in each iteration of BlackBody.")

    return parser.parse_args()


def args_var_bb_fpa():
    parser = _args_base('Set the oven to the highest temperature possible and cycle the Blackbody to different Tbb.'
                        'The images are saved as a dict in a pickle file.')
    # camera
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--lens_number', help=f"The lens number for calibration.", type=int, required=True)
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)
    parser.add_argument('--ffc', type=int, required=False, default=0,
                        help=f"The camera performs FFC before every stop if arg is 0, else at the given temperature."
                             f"The temperature is in [100C].")

    # blackbody
    parser = _args_bb_basic(parser)
    parser.add_argument('--blackbody_increments', type=float, required=True,
                        help=f"The increments in the Blackbody temperature. Allowed values [0.1, 10] C")
    parser.add_argument('--blackbody_start', type=int,
                        help="The starting temperature for the first Blackbody iteration.")
    parser.add_argument('--blackbody_is_decreasing', action='store_true',
                        help="If True, the Blackbody first iteration will have decreasing temperatures.")

    return parser.parse_args()


def args_fpa_with_ffc():
    parser = _args_base('Set the oven to a given temperature and waits for settling. Then, FFC is performed and the'
                        'Blackbody begins to oscillate.')
    # camera
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--lens_number', help=f"The lens number for calibration.", type=int, required=True)

    parser.add_argument('--time_to_collect', help=f"The time to collect measurements in Minute.",
                        type=int, required=True)
    parser.add_argument('--oven_temperature', type=int, required=True,
                        help=f"What Oven temperatures will be set. If 0 than oven will be dummy. Should be in [C].")
    parser.add_argument('--settling_time', help=f"The time in Minutes to wait for the camera temperature to settle "
                                                f"in an Oven setpoint before measurement.", type=int, default=10)

    # blackbody
    parser = _args_bb_basic(parser)
    parser.add_argument('--blackbody_increments', type=float, required=True,
                        help=f"The increments in the Blackbody temperature. Allowed values [0.1, 10] C")
    parser.add_argument('--blackbody_start', type=int,
                        help="The starting temperature for the first Blackbody iteration.")
    parser.add_argument('--blackbody_is_decreasing', action='store_true',
                        help="If True, the Blackbody first iteration will have decreasing temperatures.")

    parser.add_argument('--minutes_in_chunk', type=int, default=5,
                        help="The number of minutes to save in each chunk.")
    return parser.parse_args()


def args_const_tbb():
    parser = _args_base('Set the oven to the highest temperature possible and measure a constant Blackbody temperature.'
                        ' The images are saved as a dict in a pickle file.')

    # camera
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--rate', help=f"The rate in Hz. The maximal value is 60Hz", type=int,
                        required=True, default=60)
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)

    # blackbody
    parser.add_argument('--blackbody', type=int, required=True,
                        help=f"A constant Blackbody temperature to set, in Celsius.")

    return parser.parse_args()


def args_const_fpa():
    parser = _args_base('Measures multiple images of the BlackBody at different setpoints, '
                        'at a predefined camera temperature. '
                        'The Oven temperature is first settled at the predefined temperature, '
                        'and when the temperature of the camera settles, '
                        'measurements of the BlackBody at different setpoints commence. '
                        'The images are saved as a dict in a pickle file.')

    parser.add_argument('--n_images', help="The number of images to capture for each point.", default=3000, type=int)

    # camera
    parser.add_argument('--ffc', type=int, required=True,
                        help=f"The camera performs FFC before every stop if arg is 0, else at the given temperature.")
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')

    # blackbody
    parser.add_argument('--blackbody_stops', type=int, default=18,
                        help=f"How many BlackBody stops between blackbody_max to blackbody_min.")
    parser.add_argument('--blackbody_max', help=f"Maximal temperature of the BlackBody in C.", type=int, default=70)
    parser.add_argument('--blackbody_min', help=f"Minimal temperature of the BlackBody in C.", type=int, default=10)
    parser.add_argument('--blackbody_dummy', help=f"Uses a dummy BlackBody.", action='store_true')

    # oven
    parser.add_argument('--oven_temperature', type=int, required=True,
                        help=f"What Oven temperatures will be set. If 0 than oven will be dummy.")
    parser.add_argument('--settling_time', help=f"The time in Minutes to wait for the camera temperature to settle "
                                                f"in an Oven setpoint before measurement.", type=int, default=30)
    return parser.parse_args()
