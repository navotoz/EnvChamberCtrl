def th_saver(t_bb_: int, images: dict, fpa: dict, housing: dict, path: Path, params_cam: dict):
    dict_results = {'camera_params': params_cam.copy(), 'measurements': {}}
    for name_of_filter in list(images.keys()):
        dict_results['measurements'].setdefault(name_of_filter, {}).setdefault('fpa', fpa.pop(name_of_filter))
        dict_results['measurements'].setdefault(name_of_filter, {}).setdefault('housing', housing.pop(name_of_filter))
        dict_results['measurements'].setdefault(name_of_filter, {}).setdefault('frames', images.pop(name_of_filter))
    pickle.dump(dict_results, open(path / f'blackbody_temperature_{t_bb_:d}.pkl', 'wb'))


def th_t_cam_getter():
    while not oven.is_connected or not camera.is_connected:
        sleep(1)
    while True:
        oven.set_camera_temperatures(fpa=camera.fpa, housing=camera.housing)
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)